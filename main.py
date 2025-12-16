from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import os
import uuid
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLEARTRIP_BASE_URL = os.getenv("CLEARTRIP_BASE_URL", "https://b2b.cleartrip.com")
CLEARTRIP_API_KEY = os.getenv("CLEARTRIP_API_KEY", "")

@app.get("/")
async def root():
    return {
        "service": "Cleartrip Relay",
        "status": "running",
        "version": "2.0.0",
        "apis_supported": ["B2B V4 - All Endpoints"],
        "endpoints": {
            "content": [
                "/locations",
                "/location/hotels", 
                "/hotel-profile",
                "/incremental-updates"
            ],
            "search": [
                "/search",
                "/search-by-location"
            ],
            "booking": [
                "/detail",
                "/provisional-book",
                "/book",
                "/trip",
                "/cancel",
                "/refund-info"
            ]
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "base_url": CLEARTRIP_BASE_URL,
        "api_key_configured": bool(CLEARTRIP_API_KEY)
    }

@app.get("/api/db-test")
async def test_db():
    """Test database connection"""
    try:
        import pytds
        
        conn = pytds.connect(
            dsn=os.getenv('DB_SERVER', 'g8trip-locations-server.database.windows.net'),
            database=os.getenv('DB_NAME', 'locationsDb_cleartrip'),
            user=os.getenv('DB_USER', 'g8Triplocations'),
            password=os.getenv('DB_PASSWORD', ''),
            port=1433,
            as_dict=True,
            cafile='/etc/ssl/certs/ca-certificates.crt',
            validate_host=False
        )
        
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        conn.close()
        
        return {
            "status": "connected",
            "result": result['test'],
            "message": "Database connection successful!"
        }
    except Exception as e:
        return {
            "status": "error", 
            "message": str(e)
        }

def get_required_headers(path: str, method: str) -> dict:
    """
    Intelligently determine which headers are required for each endpoint
    based on Cleartrip B2B V4 API documentation
    """
    headers = {
        "Content-Type": "application/json",
        "x-ct-api-key": CLEARTRIP_API_KEY,
        "x-request-id": str(uuid.uuid4()),
    }
    
    path_lower = path.lower()
    
    # 1. x-meta-data header (ONLY for specific Content API endpoints)
    # Required for: /location/hotels (get hotel list by location)
    # NOT required for: /locations (get location list)
    if "location/hotels" in path_lower:
        headers["x-meta-data"] = '{"locationVersion":"V2"}'
        logger.info(f"✅ Added x-meta-data for hotel list endpoint")
    
    # 2. x-lineage-id header (Required for Search, Details, and Booking endpoints)
    needs_lineage = any([
        "search" in path_lower and "location" not in path_lower,  # /search endpoint
        "search-by-location" in path_lower,  # /search-by-location endpoint
        "/detail" in path_lower,  # /detail endpoint
        "provisional-book" in path_lower,  # /provisional-book endpoint
        "/book" in path_lower and "provisional" not in path_lower,  # /book endpoint
    ])
    
    if needs_lineage:
        headers["x-lineage-id"] = str(uuid.uuid4())
        logger.info(f"✅ Added x-lineage-id for search/booking endpoint")
    
    return headers


@app.api_route("/api/cleartrip/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def relay(path: str, request: Request):
    """
    Universal relay for all Cleartrip B2B V4 APIs
    Automatically adds correct headers based on endpoint
    """
    try:
        # Parse request body for POST/PUT
        body = None
        if request.method in ["POST", "PUT"]:
            try:
                body = await request.json()
            except:
                pass
        
        # Get query parameters
        params = dict(request.query_params)
        
        # Get required headers for this specific endpoint
        headers = get_required_headers(path, request.method)
        
        # Build full URL
        full_url = f"{CLEARTRIP_BASE_URL}/{path}"
        
        # Log request details
        logger.info(f"🔍 === CLEARTRIP API REQUEST ===")
        logger.info(f"Method: {request.method}")
        logger.info(f"Endpoint: /{path}")
        logger.info(f"URL: {full_url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Params: {params}")
        if body:
            logger.info(f"Body: {str(body)[:500]}")
        
        # Make request to Cleartrip
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=request.method,
                url=full_url,
                json=body,
                params=params,
                headers=headers
            )
            
            # Log response
            logger.info(f"📡 === CLEARTRIP API RESPONSE ===")
            logger.info(f"Status: {response.status_code}")
            logger.info(f"Response Headers: {dict(response.headers)}")
            logger.info(f"Body Preview: {response.text[:500]}")
            
            # Return response
            try:
                response_data = response.json()
                return JSONResponse(
                    content=response_data,
                    status_code=response.status_code
                )
            except:
                # Handle non-JSON responses
                return JSONResponse(
                    content={
                        "error": "Non-JSON response from Cleartrip",
                        "status_code": response.status_code,
                        "response_text": response.text[:2000]
                    },
                    status_code=response.status_code if response.status_code >= 400 else 500
                )
            
    except httpx.TimeoutException as e:
        logger.error(f"⏱️ Timeout Error: {str(e)}")
        raise HTTPException(status_code=504, detail="Request to Cleartrip timed out")
    
    except httpx.HTTPError as e:
        logger.error(f"❌ HTTP Error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Cleartrip API Error: {str(e)}")
    
    except Exception as e:
        logger.error(f"❌ Unexpected Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# Health check with detailed status
@app.get("/api/status")
async def detailed_status():
    """Detailed status endpoint for debugging"""
    return {
        "service": "Cleartrip B2B V4 Relay",
        "status": "operational",
        "version": "2.0.0",
        "configuration": {
            "base_url": CLEARTRIP_BASE_URL,
            "api_key_present": bool(CLEARTRIP_API_KEY),
            "api_key_prefix": CLEARTRIP_API_KEY[:8] + "..." if CLEARTRIP_API_KEY else None,
        },
        "supported_endpoints": {
            "content_apis": {
                "get_locations": {
                    "path": "/hotels/api/v4/content/locations",
                    "method": "GET",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": False
                },
                "get_hotel_list": {
                    "path": "/hotels/api/v4/content/location/hotels",
                    "method": "GET",
                    "requires_x_meta_data": True,
                    "requires_x_lineage_id": False
                },
                "get_hotel_profile": {
                    "path": "/hotels/api/v4/content/hotel-profile/{hotelId}",
                    "method": "GET",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": False
                },
                "get_incremental_updates": {
                    "path": "/hotels/api/v4/content/incremental-updates",
                    "method": "GET",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": False
                }
            },
            "search_apis": {
                "search_by_hotel_ids": {
                    "path": "/hotels/api/v4/search",
                    "method": "POST",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": True
                },
                "search_by_location": {
                    "path": "/hotels/api/v4/search-by-location",
                    "method": "POST",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": True
                }
            },
            "booking_apis": {
                "get_details": {
                    "path": "/hotels/api/v4/detail",
                    "method": "POST",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": True
                },
                "provisional_book": {
                    "path": "/hotels/api/v4/provisional-book",
                    "method": "POST",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": True
                },
                "book": {
                    "path": "/hotels/api/v4/book",
                    "method": "POST",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": True
                },
                "get_trip": {
                    "path": "/hotels/api/v4/trip",
                    "method": "GET",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": False
                },
                "cancel": {
                    "path": "/hotels/api/v4/cancel/{tripID}",
                    "method": "POST",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": False
                },
                "refund_info": {
                    "path": "/hotels/api/v4/refund-info/{tripID}",
                    "method": "GET",
                    "requires_x_meta_data": False,
                    "requires_x_lineage_id": False
                }
            }
        },
        "notes": [
            "All requests automatically include x-ct-api-key and x-request-id",
            "x-meta-data is only added for /location/hotels endpoint",
            "x-lineage-id is added for search, detail, and booking endpoints",
            "Content APIs should be called during off-peak hours (1-8 AM IST)"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
