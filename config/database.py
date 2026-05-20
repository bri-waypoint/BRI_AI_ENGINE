# config/database.py
# Supabase database connection for BRI AI Engine
# Supports both Shannyn's portfolio AND one-off property searches
# FIXED: get_nearby_vault_properties now catches all LEASED
#        status variants (LEASED, LEASED_RECENT, LEASED_HISTORICAL,
#        LEASED_DATED) so no leased comps are missed in searches

import os
import math
import requests
import psycopg2
from dotenv import load_dotenv
from decimal import Decimal

load_dotenv()

def get_connection():
    """
    Get PostgreSQL connection to Supabase.
    Works locally (uses .env) AND on Streamlit Cloud (uses secrets).
    """
    try:
        import streamlit as st
        host = st.secrets["SUPABASE_HOST"]
        database = st.secrets["SUPABASE_DB"]
        user = st.secrets["SUPABASE_USER"]
        password = st.secrets["SUPABASE_PASSWORD"]
        port = int(st.secrets["SUPABASE_PORT"])
    except Exception:
        host = os.getenv('SUPABASE_HOST')
        database = os.getenv('SUPABASE_DB')
        user = os.getenv('SUPABASE_USER')
        password = os.getenv('SUPABASE_PASSWORD')
        port = int(os.getenv('SUPABASE_PORT', 5432))

    return psycopg2.connect(
        host=host,
        database=database,
        user=user,
        password=password,
        port=port,
        sslmode='require',
        connect_timeout=10
    )

def clean_value(val):
    """Convert PostgreSQL Decimal types to Python native float."""
    if isinstance(val, Decimal):
        return float(val)
    return val

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance in miles between two lat/lon points."""
    R = 3959
    lat1, lon1, lat2, lon2 = map(math.radians,
                                  [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_bounding_box(lat, lon, radius_miles):
    """Calculate lat/lon bounding box for a given radius."""
    lat_delta = (radius_miles * 1.2) / 69.0
    lon_delta = (radius_miles * 1.2) / (
        69.0 * math.cos(math.radians(lat))
    )
    return {
        'min_lat': lat - lat_delta,
        'max_lat': lat + lat_delta,
        'min_lon': lon - lon_delta,
        'max_lon': lon + lon_delta
    }

def geocode_address(address, city, state, zipcode=''):
    """
    Geocode an address using OpenStreetMap Nominatim (FREE).
    Returns (latitude, longitude) or (None, None) if not found.
    """
    full_address = f"{address}, {city}, {state}"
    if zipcode:
        full_address += f" {zipcode}"
    full_address += ", USA"

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": full_address,
        "format": "json",
        "limit": 1,
        "countrycodes": "us"
    }
    headers = {
        "User-Agent": "BRI-Geocoder/1.0 (Boise Rental Intelligence)"
    }

    try:
        response = requests.get(
            url, params=params,
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            results = response.json()
            if results:
                lat = float(results[0]['lat'])
                lon = float(results[0]['lon'])
                # Validate Idaho coordinates
                if 42.0 <= lat <= 49.0 and -117.5 <= lon <= -111.0:
                    return lat, lon
        return None, None
    except Exception as e:
        print(f"Geocoding error: {str(e)}")
        return None, None

def save_one_off_search(address, city, state, zipcode,
                        bedrooms, bathrooms, living_area,
                        year_built=None, property_type='Single Family',
                        notes='', requester_name='',
                        latitude=None, longitude=None):
    """
    Save a one-off property search to Supabase.
    Auto-geocodes if lat/lon not provided.
    Returns the saved record with ID and coordinates.
    """
    # Auto-geocode if no coordinates provided
    if not latitude or not longitude:
        print("Geocoding address...")
        latitude, longitude = geocode_address(
            address, city, state, zipcode
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO one_off_searches (
            address, city, state, zipcode,
            bedrooms, bathrooms, living_area,
            year_built, property_type, notes,
            requester_name, latitude, longitude
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        RETURNING id, latitude, longitude, created_at
    """, (
        address, city, state, zipcode,
        bedrooms, bathrooms, living_area,
        year_built, property_type, notes,
        requester_name, latitude, longitude
    ))

    row = cursor.fetchone()
    conn.commit()
    conn.close()

    return {
        'id': row[0],
        'address': address,
        'city': city,
        'state': state,
        'zipcode': zipcode,
        'bedrooms': bedrooms,
        'bathrooms': bathrooms,
        'living_area': living_area,
        'year_built': year_built,
        'property_type': property_type,
        'notes': notes,
        'requester_name': requester_name,
        'latitude': row[1],
        'longitude': row[2],
        'created_at': str(row[3])
    }

def get_recent_one_off_searches(limit=20):
    """Get the most recent one-off searches."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, address, city, state, zipcode,
               bedrooms, bathrooms, living_area,
               year_built, property_type, notes,
               requester_name, latitude, longitude,
               TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI') as created_at
        FROM one_off_searches
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
        ORDER BY created_at DESC
        LIMIT %s
    """, (limit,))

    columns = [desc[0] for desc in cursor.description]
    results = []
    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        results.append(prop)

    conn.close()
    return results

def get_nearby_vault_properties(lat, lon, radius_miles=3.0,
                                limit=100, property_types=None):
    """
    Get properties from BRI Vault within radius.
    Returns leased properties from last 15 months.
    Always returns active listings regardless of date.

    FIXED: Now catches ALL leased status variants:
    - LEASED         (set by our fixed mark_inactive_properties)
    - LEASED_RECENT  (sent directly by BrightData/Zillow)
    - LEASED_HISTORICAL (sent directly by BrightData/Zillow)
    - LEASED_DATED   (sent directly by BrightData/Zillow)
    """
    conn = get_connection()
    cursor = conn.cursor()

    if property_types is None:
        property_types = [
            'SINGLE_FAMILY', 'TOWNHOUSE', 'CONDO',
            'Single Family', 'Townhouse', 'Condo'
        ]

    bbox = get_bounding_box(lat, lon, radius_miles)
    type_placeholders = ','.join(['%s'] * len(property_types))

    query = f"""
        SELECT
            zpid as id,
            address,
            city,
            state,
            zipcode,
            bedrooms,
            bathrooms,
            living_area,
            current_price,
            listing_status,
            last_seen_date,
            days_on_market,
            home_type,
            latitude,
            longitude,
            'BRI Vault' as data_source
        FROM properties
        WHERE
            latitude IS NOT NULL
            AND longitude IS NOT NULL
            AND current_price IS NOT NULL
            AND current_price > 0
            AND CAST(latitude AS FLOAT) BETWEEN %s AND %s
            AND CAST(longitude AS FLOAT) BETWEEN %s AND %s
            AND (home_type IN ({type_placeholders})
                 OR home_type IS NULL)
            AND (
                (listing_status LIKE 'LEASED%%'
                 AND last_seen_date >= TO_CHAR(
                     CURRENT_DATE - INTERVAL '15 months',
                     'YYYY-MM-DD'))
                OR listing_status LIKE '%%ACTIVE%%'
            )
        LIMIT 500
    """

    params = (
        bbox['min_lat'], bbox['max_lat'],
        bbox['min_lon'], bbox['max_lon'],
        *property_types
    )

    cursor.execute(query, params)
    columns = [desc[0] for desc in cursor.description]
    raw_results = []

    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        raw_results.append(prop)

    conn.close()

    results = []
    for prop in raw_results:
        prop_lat = prop.get('latitude')
        prop_lon = prop.get('longitude')
        if prop_lat is None or prop_lon is None:
            continue
        try:
            dist = haversine_distance(
                lat, lon, float(prop_lat), float(prop_lon)
            )
            if dist <= radius_miles:
                prop['distance_miles'] = round(dist, 3)
                results.append(prop)
        except Exception:
            continue

    results.sort(key=lambda p: (
        0 if str(p.get('listing_status', '')).startswith('LEASED')
        else 1,
        p.get('distance_miles', 99)
    ))

    return results[:limit]

def get_nearby_rentcast_properties(lat, lon, radius_miles=3.0,
                                   limit=100, property_types=None):
    """
    Get RentCast listings from Supabase stored data.
    Only returns leased properties from last 15 months.
    Always returns active listings regardless of date.
    """
    conn = get_connection()
    cursor = conn.cursor()

    if property_types is None:
        property_types = ['Single Family', 'Townhouse', 'Condo']

    bbox = get_bounding_box(lat, lon, radius_miles)
    type_placeholders = ','.join(['%s'] * len(property_types))

    query = f"""
        SELECT
            id,
            formatted_address as address,
            city,
            state,
            zip_code as zipcode,
            bedrooms,
            bathrooms,
            square_footage as living_area,
            price as current_price,
            status as listing_status,
            last_seen_date,
            listed_date,
            removed_date,
            days_on_market,
            property_type as home_type,
            latitude,
            longitude,
            dump_date,
            'RentCast' as data_source
        FROM rentcast_listings
        WHERE
            latitude IS NOT NULL
            AND longitude IS NOT NULL
            AND price IS NOT NULL
            AND price > 0
            AND CAST(latitude AS FLOAT) BETWEEN %s AND %s
            AND CAST(longitude AS FLOAT) BETWEEN %s AND %s
            AND property_type IN ({type_placeholders})
            AND (
                (status = 'Inactive'
                 AND last_seen_date >= TO_CHAR(
                     CURRENT_DATE - INTERVAL '15 months',
                     'YYYY-MM-DD'))
                OR status = 'Active'
            )
        LIMIT 500
    """

    params = (
        bbox['min_lat'], bbox['max_lat'],
        bbox['min_lon'], bbox['max_lon'],
        *property_types
    )

    cursor.execute(query, params)
    columns = [desc[0] for desc in cursor.description]
    raw_results = []

    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        raw_results.append(prop)

    conn.close()

    results = []
    for prop in raw_results:
        prop_lat = prop.get('latitude')
        prop_lon = prop.get('longitude')
        if prop_lat is None or prop_lon is None:
            continue
        try:
            dist = haversine_distance(
                lat, lon, float(prop_lat), float(prop_lon)
            )
            if dist <= radius_miles:
                prop['distance_miles'] = round(dist, 3)
                results.append(prop)
        except Exception:
            continue

    results.sort(key=lambda p: (
        0 if p.get('listing_status') == 'Inactive' else 1,
        p.get('distance_miles', 99)
    ))

    return results[:limit]

def get_subject_properties():
    """Get all of Shannyn's subject properties with coordinates."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, address, city, state, bedrooms, bathrooms,
               living_area, latitude, longitude,
               current_rent, notes
        FROM subject_properties
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
        ORDER BY address
    """)

    columns = [desc[0] for desc in cursor.description]
    results = []
    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        results.append(prop)

    conn.close()
    return results

def get_database_stats():
    """Get stats from both vault and rentcast tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN listing_status = 'LEASED'
                  THEN 1 END) as leased,
            COUNT(CASE WHEN listing_status LIKE '%%ACTIVE%%'
                  THEN 1 END) as active
        FROM properties
    """)
    vault = cursor.fetchone()

    cursor.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN status = 'Inactive'
                  THEN 1 END) as leased,
            COUNT(CASE WHEN status = 'Active'
                  THEN 1 END) as active,
            MAX(dump_date) as last_dump
        FROM rentcast_listings
    """)
    rc = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM one_off_searches")
    one_off = cursor.fetchone()

    conn.close()

    return {
        'vault_total': vault[0],
        'vault_leased': vault[1],
        'vault_active': vault[2],
        'rentcast_total': rc[0],
        'rentcast_leased': rc[1],
        'rentcast_active': rc[2],
        'rentcast_last_dump': rc[3],
        'one_off_total': one_off[0]
    }