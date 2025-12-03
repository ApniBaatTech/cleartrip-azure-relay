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

CLEARTRIP_BASE_URL = os.getenv("CLEARTRIP_BASE_URL", "https://api.cleartrip.com")
CLEARTRIP_API_KEY = os.getenv("CLEARTRIP_API_KEY", "")

@app.get("/")
async def root():
    return {"service": "Cleartrip Relay", "status": "running", "version": "1.0.2"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cleartrip_url": CLEARTRIP_BASE_URL,
        "api_key_configured": bool(CLEARTRIP_API_KEY)
    }

@app.api_route("/api/cleartrip/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def relay(path: str, request: Request):
    """Generic relay for Cleartrip endpoints with proper headers"""
    try:
        # Get request body for POST/PUT
        body = None
        if request.method in ["POST", "PUT"]:
            try:
                body = await request.json()
            except:
                pass
        
        # Get query parameters
        params = dict(request.query_params)
        
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Cleartrip required headers
        headers = {
            "Content-Type": "application/json",
            "x-ct-api-key": CLEARTRIP_API_KEY,
            "x-request-id": request_id,
            "x-meta-data": '{"locationVersion":"V2"}'
        }
        
        # Build full URL
        full_url = f"{CLEARTRIP_BASE_URL}/{path}"
        
        logger.info(f"Calling Cleartrip: {request.method} {full_url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Params: {params}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=full_url,
                json=body,
                params=params,
                headers=headers
            )
            
            logger.info(f"Cleartrip Status: {response.status_code}")
            logger.info(f"Cleartrip Response Text: {response.text[:500]}")
            
            # Check if response is JSON
            try:
                response_data = response.json()
            except:
                # Not JSON - return as text
                return JSONResponse(
                    content={
                        "error": "Non-JSON response from Cleartrip",
                        "status_code": response.status_code,
                        "response_text": response.text[:1000]
                    },
                    status_code=response.status_code
                )
            
            return JSONResponse(
                content=response_data,
                status_code=response.status_code
            )
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP Error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Cleartrip API Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
