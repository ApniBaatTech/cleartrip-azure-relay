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

# Keep your existing B2B URL
CLEARTRIP_BASE_URL = os.getenv("CLEARTRIP_BASE_URL", "https://b2b.cleartrip.com")
CLEARTRIP_API_KEY = os.getenv("CLEARTRIP_API_KEY", "")

# Add SaaS API URL
CLEARTRIP_SAAS_URL = "https://saasapi.cleartrip.com"

@app.get("/")
async def root():
    return {
        "service": "Cleartrip Relay", 
        "status": "running", 
        "version": "1.0.7",  # ✅ Updated version
        "apis_supported": ["B2B V4", "SaaS"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "b2b_url": CLEARTRIP_BASE_URL,
        "saas_url": CLEARTRIP_SAAS_URL,
        "api_key_configured": bool(CLEARTRIP_API_KEY)
    }

@app.api_route("/api/cleartrip/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def relay(path: str, request: Request):
    """Generic relay for Cleartrip B2B V4 APIs (EXISTING - WORKS!)"""
    try:
        body = None
        if request.method in ["POST", "PUT"]:
            try:
                body = await request.json()
            except:
                pass
        
        params = dict(request.query_params)
        request_id = str(uuid.uuid4())
        
        headers = {
            "Content-Type": "application/json",
            "x-ct-api-key": CLEARTRIP_API_KEY,
            "x-request-id": request_id,
        }
        
        if "content" in path.lower():
            headers["x-meta-data"] = '{"locationVersion":"V2"}'
            logger.info(f"✅ Added x-meta-data for content API")
        
        needs_lineage = (
            "search" in path.lower() or 
            "detail" in path.lower() or 
            "provisional-book" in path.lower() or 
            "book" in path.lower()
        )
        
        if needs_lineage:
            headers["x-lineage-id"] = str(uuid.uuid4())
            logger.info(f"✅ Added x-lineage-id")
        
        full_url = f"{CLEARTRIP_BASE_URL}/{path}"
        
        logger.info(f"🔍 === REQUEST ===")
        logger.info(f"Method: {request.method}")
        logger.info(f"URL: {full_url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Params: {params}")
        if body:
            logger.info(f"Body: {str(body)[:500]}")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=request.method,
                url=full_url,
                json=body,
                params=params,
                headers=headers
            )
            
            logger.info(f"📡 === RESPONSE ===")
            logger.info(f"Status: {response.status_code}")
            logger.info(f"Headers: {dict(response.headers)}")
            logger.info(f"Body: {response.text[:1000]}")
            
            try:
                response_data = response.json()
                return JSONResponse(
                    content=response_data,
                    status_code=response.status_code
                )
            except:
                return JSONResponse(
                    content={
                        "error": "Non-JSON response",
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
