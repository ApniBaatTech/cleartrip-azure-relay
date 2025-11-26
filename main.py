import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    return {"service": "Cleartrip Relay", "status": "running"}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "cleartrip_url": CLEARTRIP_BASE_URL,
        "api_key_configured": bool(CLEARTRIP_API_KEY),
    }


@app.api_route("/api/cleartrip/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def relay(path: str, request: Request):
    try:
        body = None
        if request.method in ["POST", "PUT"]:
            body = await request.json()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=request.method,
                url=f"{CLEARTRIP_BASE_URL}/{path}",
                json=body,
                params=dict(request.query_params),
                headers={
                    "Authorization": f"Bearer {CLEARTRIP_API_KEY}",
                    "Content-Type": "application/json",
                },
            )

            return JSONResponse(
                content=response.json() if response.text else {},
                status_code=response.status_code,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
