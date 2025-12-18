from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import os
import uuid
import logging
import pytds

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


# ============== DATABASE HELPER ==============

def get_db_connection():
    """Create database connection"""
    return pytds.connect(
        dsn=os.getenv('DB_SERVER', 'g8trip-locations-server.database.windows.net'),
        database=os.getenv('DB_NAME', 'locationsDb_cleartrip'),
        user=os.getenv('DB_USER', 'g8Triplocations'),
        password=os.getenv('DB_PASSWORD', ''),
        port=1433,
        as_dict=True,
        cafile='/etc/ssl/certs/ca-certificates.crt',
        validate_host=False
    )


# ============== ROOT & HEALTH ENDPOINTS ==============

@app.get("/")
async def root():
    return {
        "service": "Cleartrip Relay",
        "status": "running",
        "version": "2.1.0",
        "apis_supported": ["B2B V4 - All Endpoints", "Locations DB"],
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
            ],
            "database": [
                "/api/db-test",
                "/api/locations/autocomplete",
                "/api/locations/all",
                "/api/locations/{id}"
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
        conn = get_db_connection()
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


# ============== LOCATIONS ENDPOINTS ==============

# ============== LOCATIONS ENDPOINTS ==============

@app.get("/api/locations/autocomplete")
async def autocomplete_locations(q: str = "", limit: int = 10):
    """
    Search locations by name prefix for autocomplete
    
    Usage: /api/locations/autocomplete?q=kor&limit=10
    """
    try:
        if len(q) < 2:
            return {
                "status": "error",
                "message": "Query must be at least 2 characters",
                "query": q,
                "locations": []
            }
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # FIX: Pass parameters as tuple, use LIKE pattern correctly
        search_pattern = f"{q}%"
        cursor.execute("""
            SELECT TOP(?) id, name, type, parent_id, latitude, longitude
            FROM locations 
            WHERE name LIKE ? AND search_enabled = 1
            ORDER BY 
                CASE type 
                    WHEN 'CITY' THEN 1 
                    WHEN 'LOCALITY' THEN 2 
                    WHEN 'STATE' THEN 3 
                    WHEN 'COUNTRY' THEN 4 
                END,
                name
        """, (limit, search_pattern))  # ✅ Pass as tuple with pre-formatted pattern
        
        results = cursor.fetchall()
        conn.close()
        
        return {
            "status": "success",
            "query": q,
            "count": len(results),
            "locations": results
        }
        
    except Exception as e:
        logger.error(f"Autocomplete error: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "query": q,
            "locations": []
        }


@app.get("/api/locations/all")
async def get_all_locations(limit: int = 100, offset: int = 0, type: str = None):
    """
    Get all locations with pagination
    
    Usage: /api/locations/all?limit=100&offset=0&type=CITY
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query based on type filter
        if type:
            # FIX: Ensure all parameters are in tuple
            cursor.execute("""
                SELECT id, name, type, parent_id, latitude, longitude, search_enabled
                FROM locations 
                WHERE type = ?
                ORDER BY name
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """, (type, offset, limit))  # ✅ All three params in tuple
        else:
            # FIX: Pass offset and limit as tuple
            cursor.execute("""
                SELECT id, name, type, parent_id, latitude, longitude, search_enabled
                FROM locations 
                ORDER BY type, name
                OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """, (offset, limit))  # ✅ Both params in tuple
        
        results = cursor.fetchall()
        
        # Get total count
        if type:
            cursor.execute("SELECT COUNT(*) as total FROM locations WHERE type = ?", (type,))  # ✅ Single value still needs tuple
        else:
            cursor.execute("SELECT COUNT(*) as total FROM locations")  # ✅ No params needed
        
        total = cursor.fetchone()['total']
        conn.close()
        
        return {
            "status": "success",
            "total": total,
            "limit": limit,
            "offset": offset,
            "type_filter": type,
            "locations": results
        }
        
    except Exception as e:
        logger.error(f"Get all locations error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/api/locations/{location_id}")
async def get_location_by_id(location_id: int):
    """
    Get single location by ID with parent details
    
    Usage: /api/locations/432610
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the location - FIX: Single param still needs tuple
        cursor.execute("""
            SELECT id, name, type, parent_id, latitude, longitude, search_enabled
            FROM locations 
            WHERE id = ?
        """, (location_id,))  # ✅ Tuple with single value
        
        location = cursor.fetchone()
        
        if not location:
            conn.close()
            return {
                "status": "error",
                "message": f"Location {location_id} not found"
            }
        
        # Get parent hierarchy
        hierarchy = []
        parent_id = location['parent_id']
        
        while parent_id:
            cursor.execute("""
                SELECT id, name, type, parent_id
                FROM locations 
                WHERE id = ?
            """, (parent_id,))  # ✅ Tuple with single value
            
            parent = cursor.fetchone()
            if parent:
                hierarchy.append(parent)
                parent_id = parent['parent_id']
            else:
                break
        
        conn.close()
        
        return {
            "status": "success",
            "location": location,
            "hierarchy": hierarchy
        }
        
    except Exception as e:
        logger.error(f"Get location error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


# ============== CLEARTRIP RELAY ==============

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
    
    if "location/hotels" in path_lower:
        headers["x-meta-data"] = '{"locationVersion":"V2"}'
        logger.info(f"✅ Added x-meta-data for hotel list endpoint")
    
    needs_lineage = any([
        "search" in path_lower and "location" not in path_lower,
        "search-by-location" in path_lower,
        "/detail" in path_lower,
        "provisional-book" in path_lower,
        "/book" in path_lower and "provisional" not in path_lower,
    ])
    
    if needs_lineage:
        headers["x-lineage-id"] = str(uuid.uuid4())
        logger.info(f"✅ Added x-lineage-id for search/booking endpoint")
    
    return headers


@app.api_route("/api/cleartrip/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def relay(path: str, request: Request):
    """
    Universal relay for all Cleartrip B2B V4 APIs
    """
    try:
        body = None
        if request.method in ["POST", "PUT"]:
            try:
                body = await request.json()
            except:
                pass
        
        params = dict(request.query_params)
        headers = get_required_headers(path, request.method)
        full_url = f"{CLEARTRIP_BASE_URL}/{path}"
        
        logger.info(f"🔍 === CLEARTRIP API REQUEST ===")
        logger.info(f"Method: {request.method}")
        logger.info(f"Endpoint: /{path}")
        logger.info(f"URL: {full_url}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=request.method,
                url=full_url,
                json=body,
                params=params,
                headers=headers
            )
            
            logger.info(f"📡 Response Status: {response.status_code}")
            
            try:
                response_data = response.json()
                return JSONResponse(
                    content=response_data,
                    status_code=response.status_code
                )
            except:
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


@app.get("/api/status")
async def detailed_status():
    """Detailed status endpoint for debugging"""
    return {
        "service": "Cleartrip B2B V4 Relay",
        "status": "operational",
        "version": "2.1.0",
        "configuration": {
            "base_url": CLEARTRIP_BASE_URL,
            "api_key_present": bool(CLEARTRIP_API_KEY),
            "api_key_prefix": CLEARTRIP_API_KEY[:8] + "..." if CLEARTRIP_API_KEY else None,
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
