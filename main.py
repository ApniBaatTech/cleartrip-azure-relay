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
        "version": "2.0.1",
        "apis_supported": ["B2B V4"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "base_url": CLEARTRIP_BASE_URL,
        "api_key_configured": bool(CLEARTRIP_API_KEY)
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
    
    # 1. x-meta-data header (ONLY for /location/hotels endpoint)
    if "location/hotels" in path_lower:
        headers["x-meta-data"] = '{"locationVersion":"V2"}'
        logger.info(f"✅ Added x-meta-data for hotel list endpoint")
    
    # 2. x-lineage-id header (Required for Search, Details, and Booking endpoints)
    needs_lineage = any([
        path_lower.endswith("/search") or "/search?" in path_lower,  # /search endpoint
        "search-by-location" in path_lower,  # /search-by-location endpoint
        "/detail" in path_lower,  # /detail endpoint
        "provisional-book" in path_lower,  # /provisional-book endpoint
        path_lower.endswith("/book") or "/book?" in path_lower,  # /book endpoint only
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
