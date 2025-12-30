from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import os
import uuid
import logging
import pytds
from typing import Optional
from datetime import datetime, timedelta

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

# Environment variables
CLEARTRIP_BASE_URL = os.getenv("CLEARTRIP_BASE_URL", "https://b2b.cleartrip.com")
CLEARTRIP_FLIGHT_BASE_URL = os.getenv("CLEARTRIP_FLIGHT_BASE_URL", "https://api.cleartrip.com/air/api/v4")
CLEARTRIP_API_KEY = os.getenv("CLEARTRIP_API_KEY", "")

# Flight API credentials
FLIGHT_EMAIL = os.getenv("CLEARTRIP_FLIGHT_EMAIL", "ss@apnibaat.in")
FLIGHT_PASSWORD = os.getenv("CLEARTRIP_FLIGHT_PASSWORD", "test31@Max")
FLIGHT_TENANT_ID = os.getenv("CLEARTRIP_FLIGHT_TENANT_ID", "MonetizeMax-7xt09")

# In-memory token storage (for single instance)
# For production with multiple instances, use Redis or database
flight_token_cache = {
    "idToken": None,
    "refreshToken": None,
    "expiresAt": None
}


# ============== FLIGHT API TOKEN MANAGEMENT ==============

async def get_flight_token():
    """
    Get valid flight API token, refresh if expired
    """
    global flight_token_cache
    
    # Check if we have a valid token
    if (flight_token_cache["idToken"] and 
        flight_token_cache["expiresAt"] and 
        datetime.now() < flight_token_cache["expiresAt"]):
        logger.info("✅ Using cached flight token")
        return flight_token_cache["idToken"]
    
    # Need to login or refresh
    logger.info("🔐 Flight token expired or missing, logging in...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/login",
                json={
                    "email": FLIGHT_EMAIL,
                    "password": FLIGHT_PASSWORD,
                    "tenantId": FLIGHT_TENANT_ID
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Cache the tokens
                flight_token_cache["idToken"] = data["idToken"]
                flight_token_cache["refreshToken"] = data["refreshToken"]
                # Set expiry 5 minutes before actual expiry for safety
                expires_in = int(data.get("expiresIn", 3600)) - 300
                flight_token_cache["expiresAt"] = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info(f"✅ Flight login successful! Token expires at {flight_token_cache['expiresAt']}")
                return flight_token_cache["idToken"]
            else:
                logger.error(f"❌ Flight login failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Flight API login failed: {response.text}"
                )
                
    except Exception as e:
        logger.error(f"❌ Error getting flight token: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Token error: {str(e)}")


async def refresh_flight_token():
    """
    Refresh the flight API token using refresh token
    """
    global flight_token_cache
    
    if not flight_token_cache["refreshToken"]:
        logger.warning("⚠️ No refresh token available, doing full login")
        return await get_flight_token()
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/refresh",
                json={"refreshToken": flight_token_cache["refreshToken"]},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {flight_token_cache['idToken']}"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Update cached token
                flight_token_cache["idToken"] = data["idToken"]
                expires_in = int(data.get("expiresIn", 3600)) - 300
                flight_token_cache["expiresAt"] = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info(f"✅ Flight token refreshed! Expires at {flight_token_cache['expiresAt']}")
                return flight_token_cache["idToken"]
            else:
                # Refresh failed, do full login
                logger.warning("⚠️ Token refresh failed, doing full login")
                return await get_flight_token()
                
    except Exception as e:
        logger.error(f"❌ Error refreshing token: {str(e)}")
        return await get_flight_token()


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
        "version": "3.0.0",
        "apis_supported": [
            "B2B V4 Hotels - All Endpoints",
            "Flight API V4 - All Endpoints",
            "Locations DB"
        ],
        "endpoints": {
            "hotels": {
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
            },
            "flights": {
                "auth": [
                    "/api/flights/login",
                    "/api/flights/refresh"
                ],
                "search": [
                    "/api/flights/search",
                    "/api/flights/airports"
                ],
                "booking": [
                    "/api/flights/session",
                    "/api/flights/preview",
                    "/api/flights/hold",
                    "/api/flights/book"
                ],
                "extras": [
                    "/api/flights/ancillary",
                    "/api/flights/fare-benefits",
                    "/api/flights/fare-calendar"
                ]
            },
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
        "flight_base_url": CLEARTRIP_FLIGHT_BASE_URL,
        "api_key_configured": bool(CLEARTRIP_API_KEY),
        "flight_credentials_configured": bool(FLIGHT_EMAIL and FLIGHT_PASSWORD and FLIGHT_TENANT_ID),
        "flight_token_cached": bool(flight_token_cache["idToken"]),
        "flight_token_expires_at": flight_token_cache["expiresAt"].isoformat() if flight_token_cache["expiresAt"] else None
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


# ============== FLIGHT API ENDPOINTS ==============

@app.post("/api/flights/login")
async def flight_login():
    """
    Login to Cleartrip Flight API and get authentication tokens
    """
    try:
        token = await get_flight_token()
        
        return {
            "success": True,
            "data": {
                "email": FLIGHT_EMAIL,
                "idToken": token,
                "refreshToken": flight_token_cache["refreshToken"],
                "expiresAt": flight_token_cache["expiresAt"].isoformat()
            }
        }
    except Exception as e:
        logger.error(f"❌ Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/refresh")
async def flight_refresh():
    """
    Refresh the flight API token
    """
    try:
        token = await refresh_flight_token()
        
        return {
            "success": True,
            "data": {
                "idToken": token,
                "expiresAt": flight_token_cache["expiresAt"].isoformat()
            }
        }
    except Exception as e:
        logger.error(f"❌ Refresh error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/search")
async def flight_search(request: Request):
    """
    Search for flights
    
    Body example:
    {
        "searchQuery": {
            "cabinClass": "ECONOMY",
            "paxInfo": {"adults": 1, "children": 0, "infants": 0}
        },
        "routeInfos": [{
            "fromCityOrAirport": {"code": "DEL"},
            "toCityOrAirport": {"code": "BOM"},
            "travelDate": "2025-02-15"
        }]
    }
    """
    try:
        token = await get_flight_token()
        body = await request.json()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/search",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Search error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/session")
async def flight_session(request: Request):
    """
    Create a session for booking flow
    
    Body: {"searchId": "search_12345"}
    """
    try:
        token = await get_flight_token()
        body = await request.json()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/session",
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Session error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/preview")
async def flight_preview(request: Request):
    """
    Get flight preview details
    
    Headers: x-ct-session-id
    Body: {"travelOptionId": "option_123"}
    """
    try:
        token = await get_flight_token()
        body = await request.json()
        session_id = request.headers.get("x-ct-session-id")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if session_id:
            headers["x-ct-session-id"] = session_id
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/preview",
                json=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Preview error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/hold")
async def flight_hold(request: Request):
    """
    Hold a flight (lock the fare)
    
    Headers: x-ct-session-id
    Body: {passenger and contact details}
    """
    try:
        token = await get_flight_token()
        body = await request.json()
        session_id = request.headers.get("x-ct-session-id")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if session_id:
            headers["x-ct-session-id"] = session_id
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/hold",
                json=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Hold error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/book")
async def flight_book(request: Request):
    """
    Book a flight (create PNR)
    
    Headers: x-ct-session-id
    Body: {"travelId": "travel_xyz"}
    """
    try:
        token = await get_flight_token()
        body = await request.json()
        session_id = request.headers.get("x-ct-session-id")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if session_id:
            headers["x-ct-session-id"] = session_id
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/book",
                json=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Book error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/flights/ancillary")
async def flight_ancillary(request: Request):
    """
    Get ancillary services (seats, meals, baggage)
    
    Headers: x-ct-session-id
    Body: {"travelOptionId": "option_123"}
    """
    try:
        token = await get_flight_token()
        body = await request.json()
        session_id = request.headers.get("x-ct-session-id")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        if session_id:
            headers["x-ct-session-id"] = session_id
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/ancillary",
                json=body,
                headers=headers
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Ancillary error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/flights/airports")
async def flight_airports(query: str = ""):
    """
    Airport autocomplete search
    
    Query param: query (e.g., ?query=del)
    """
    try:
        token = await get_flight_token()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/airport-suggest",
                params={"query": query},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Airport search error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/flights/fare-calendar")
async def flight_fare_calendar(origin: str, destination: str, date: str):
    """
    Get fare calendar for route
    
    Query params: origin, destination, date
    """
    try:
        token = await get_flight_token()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{CLEARTRIP_FLIGHT_BASE_URL}/fare-calendar",
                params={
                    "origin": origin,
                    "destination": destination,
                    "date": date
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )
            
            return JSONResponse(
                content=response.json(),
                status_code=response.status_code
            )
            
    except Exception as e:
        logger.error(f"❌ Fare calendar error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== LOCATIONS ENDPOINTS (keeping existing) ==============

@app.get("/api/locations/autocomplete")
async def autocomplete_locations(q: str = "", limit: int = 10):
    """Search locations by name prefix for autocomplete"""
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
        
        search_pattern = f"{q}%"
        query = f"""
            SELECT TOP({limit}) id, name, type, parent_id, latitude, longitude
            FROM locations 
            WHERE name LIKE %s AND search_enabled = 1
            ORDER BY 
                CASE type 
                    WHEN 'CITY' THEN 1 
                    WHEN 'LOCALITY' THEN 2 
                    WHEN 'STATE' THEN 3 
                    WHEN 'COUNTRY' THEN 4 
                END,
                name
        """
        
        cursor.execute(query, (search_pattern,))
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
    """Get all locations with pagination"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if type:
            query = f"""
                SELECT id, name, type, parent_id, latitude, longitude, search_enabled
                FROM locations 
                WHERE type = %s
                ORDER BY name
                OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY
            """
            cursor.execute(query, (type,))
        else:
            query = f"""
                SELECT id, name, type, parent_id, latitude, longitude, search_enabled
                FROM locations 
                ORDER BY type, name
                OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY
            """
            cursor.execute(query)
        
        results = cursor.fetchall()
        
        if type:
            cursor.execute("SELECT COUNT(*) as total FROM locations WHERE type = %s", (type,))
        else:
            cursor.execute("SELECT COUNT(*) as total FROM locations")
        
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
    """Get single location by ID with parent details"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, type, parent_id, latitude, longitude, search_enabled
            FROM locations 
            WHERE id = %s
        """, (location_id,))
        
        location = cursor.fetchone()
        
        if not location:
            conn.close()
            return {
                "status": "error",
                "message": f"Location {location_id} not found"
            }
        
        hierarchy = []
        parent_id = location['parent_id']
        
        while parent_id:
            cursor.execute("""
                SELECT id, name, type, parent_id
                FROM locations 
                WHERE id = %s
            """, (parent_id,))
            
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


# ============== HOTELS ENDPOINTS (keeping existing) ==============

@app.get("/api/hotel-search")
async def search_hotels(q: str = "", location_id: int = None, min_rating: float = None, limit: int = 20):
    """Search hotels by name or filter by location/rating"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if q and len(q) >= 2:
            conditions.append("h.name LIKE %s")
            params.append(f"%{q}%")
        
        if location_id:
            conditions.append("h.location_id = %s")
            params.append(location_id)
        
        if min_rating:
            conditions.append("h.star_rating >= %s")
            params.append(min_rating)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT TOP({limit}) h.id, h.name, h.star_rating, h.property_type, 
                   h.address, h.latitude, h.longitude, h.images,
                   l.name as city_name
            FROM hotels h
            JOIN locations l ON h.location_id = l.id
            WHERE {where_clause}
            ORDER BY h.star_rating DESC, h.name
        """
        
        cursor.execute(query, tuple(params))
        hotels = cursor.fetchall()
        conn.close()
        
        return {
            "status": "success",
            "query": q,
            "filters": {
                "location_id": location_id,
                "min_rating": min_rating
            },
            "count": len(hotels),
            "hotels": hotels
        }
        
    except Exception as e:
        logger.error(f"Search hotels error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/api/hotels/by-location/{location_id}")
async def get_hotels_by_location(location_id: int, limit: int = 50, offset: int = 0):
    """Get all hotels for a specific location"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, type FROM locations WHERE id = %s
        """, (location_id,))
        
        location = cursor.fetchone()
        
        if not location:
            conn.close()
            return {
                "status": "error",
                "message": f"Location {location_id} not found"
            }
        
        query = f"""
            SELECT id, name, star_rating, property_type, address, pincode,
                   latitude, longitude, total_rooms, total_floors,
                   check_in_time, check_out_time, images, amenities
            FROM hotels 
            WHERE location_id = %s
            ORDER BY star_rating DESC, name
            OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY
        """
        cursor.execute(query, (location_id,))
        hotels = cursor.fetchall()
        
        cursor.execute("SELECT COUNT(*) as total FROM hotels WHERE location_id = %s", (location_id,))
        total = cursor.fetchone()['total']
        
        conn.close()
        
        return {
            "status": "success",
            "location": location,
            "total_hotels": total,
            "limit": limit,
            "offset": offset,
            "hotels": hotels
        }
        
    except Exception as e:
        logger.error(f"Get hotels by location error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/api/hotels/{hotel_id}")
async def get_hotel_by_id(hotel_id: int):
    """Get single hotel with all details including rooms"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT h.*, l.name as city_name, l.type as city_type
            FROM hotels h
            JOIN locations l ON h.location_id = l.id
            WHERE h.id = %s
        """, (hotel_id,))
        
        hotel = cursor.fetchone()
        
        if not hotel:
            conn.close()
            return {
                "status": "error",
                "message": f"Hotel {hotel_id} not found"
            }
        
        cursor.execute("""
            SELECT id, name, area_value, area_unit, max_occupancy, 
                   max_adults, max_children, amenities, images
            FROM hotel_rooms 
            WHERE hotel_id = %s
            ORDER BY name
        """, (hotel_id,))
        
        rooms = cursor.fetchall()
        conn.close()
        
        return {
            "status": "success",
            "hotel": hotel,
            "rooms": rooms
        }
        
    except Exception as e:
        logger.error(f"Get hotel error: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


# ============== CLEARTRIP HOTEL RELAY (keeping existing) ==============

def get_required_headers(path: str, method: str) -> dict:
    """Determine required headers for hotel endpoints"""
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
    """Universal relay for all Cleartrip B2B V4 Hotel APIs"""
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
        
        logger.info(f"🔍 === CLEARTRIP HOTEL API REQUEST ===")
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
        "service": "Cleartrip B2B V4 + Flight API Relay",
        "status": "operational",
        "version": "3.0.0",
        "configuration": {
            "hotels": {
                "base_url": CLEARTRIP_BASE_URL,
                "api_key_present": bool(CLEARTRIP_API_KEY),
                "api_key_prefix": CLEARTRIP_API_KEY[:8] + "..." if CLEARTRIP_API_KEY else None,
            },
            "flights": {
                "base_url": CLEARTRIP_FLIGHT_BASE_URL,
                "email": FLIGHT_EMAIL,
                "tenant_id": FLIGHT_TENANT_ID,
                "token_cached": bool(flight_token_cache["idToken"]),
                "token_expires_at": flight_token_cache["expiresAt"].isoformat() if flight_token_cache["expiresAt"] else None
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
