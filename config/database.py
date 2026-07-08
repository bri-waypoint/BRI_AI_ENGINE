# config/database.py
# Supabase database connection for BRI AI Engine
# Supports both Shannyn's portfolio AND one-off property searches
# UPDATED: Four-round appraisal-method comp search
#          Round 1: 1 mile, 15 months, tight similarity
#          Round 2: 2 miles, 24 months, tight similarity
#          Round 3: 3 miles, 24 months, similar residential
#          Round 4: 5 miles, 24 months, relaxed similarity
# ADDED: save/load property notes per subject property
# ADDED: save/load analysis reports per subject property

import os
import math
import json
import requests
import psycopg2
from dotenv import load_dotenv
from decimal import Decimal
from datetime import datetime, timedelta

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
                if 42.0 <= lat <= 49.0 and -117.5 <= lon <= -111.0:
                    return lat, lon
        return None, None
    except Exception as e:
        print(f"Geocoding error: {str(e)}")
        return None, None

# ============================================================
# PROPERTY TYPE HELPERS
# ============================================================

# Normalize all vault and rentcast type variants to
# canonical groups for consistent similarity matching
SINGLE_FAMILY_TYPES = {
    'SINGLE_FAMILY', 'SINGLEFAMILY', 'Single Family'
}
TOWNHOUSE_TYPES = {
    'TOWNHOUSE', 'TOWNHOME', 'Townhouse'
}
CONDO_TYPES = {
    'CONDO', 'Condo'
}
ALL_RESIDENTIAL_TYPES = (
    SINGLE_FAMILY_TYPES |
    TOWNHOUSE_TYPES |
    CONDO_TYPES
)
# Never used for comps
EXCLUDED_TYPES = {'APARTMENT', 'Multi-Family', 'MULTI_FAMILY'}

def get_type_group(home_type):
    """Return canonical group name for a property type."""
    t = str(home_type or '').strip()
    if t in SINGLE_FAMILY_TYPES:
        return 'Single Family'
    if t in TOWNHOUSE_TYPES:
        return 'Townhouse'
    if t in CONDO_TYPES:
        return 'Condo'
    return None

def get_same_type_variants(home_type):
    """Return all database variants for the same type group."""
    group = get_type_group(home_type)
    if group == 'Single Family':
        return list(SINGLE_FAMILY_TYPES)
    if group == 'Townhouse':
        return list(TOWNHOUSE_TYPES)
    if group == 'Condo':
        return list(CONDO_TYPES)
    return list(ALL_RESIDENTIAL_TYPES)

def passes_similarity(prop, subject_beds, subject_baths,
                      subject_sqft, subject_type_group,
                      sqft_tolerance=0.15, bed_tolerance=1,
                      same_type_only=True):
    """
    Check if a property passes similarity criteria.
    Returns True if the property is similar enough to use as a comp.
    """
    # Type check
    prop_type = get_type_group(prop.get('home_type', ''))
    if same_type_only:
        if prop_type != subject_type_group:
            return False
    else:
        # In relaxed rounds still exclude apartments
        raw_type = str(prop.get('home_type', '') or '')
        if raw_type in EXCLUDED_TYPES:
            return False

    # Bedroom check
    prop_beds = prop.get('bedrooms')
    if prop_beds is not None and subject_beds is not None:
        try:
            if abs(float(prop_beds) - float(subject_beds)) > bed_tolerance:
                return False
        except (TypeError, ValueError):
            pass

    # Bathroom check — always within 0.5
    prop_baths = prop.get('bathrooms')
    if prop_baths is not None and subject_baths is not None:
        try:
            if abs(float(prop_baths) - float(subject_baths)) > 0.5:
                return False
        except (TypeError, ValueError):
            pass

    # Sqft check
    prop_sqft = prop.get('living_area')
    if prop_sqft is not None and subject_sqft is not None:
        try:
            if float(subject_sqft) > 0:
                diff = abs(
                    float(prop_sqft) - float(subject_sqft)
                ) / float(subject_sqft)
                if diff > sqft_tolerance:
                    return False
        except (TypeError, ValueError):
            pass

    return True

# ============================================================
# CORE PROPERTY FETCH - Raw geographic fetch from each table
# ============================================================

def fetch_vault_properties(lat, lon, radius_miles,
                           months_back, exclude_address=None,
                           property_types=None):
    """
    Fetch all matching vault properties within radius and date window.
    Returns leased and active separately.
    No similarity filtering here — that happens in Python.
    """
    conn = get_connection()
    cursor = conn.cursor()

    bbox = get_bounding_box(lat, lon, radius_miles)
    cutoff = (
        datetime.now() - timedelta(days=months_back * 30.5)
    ).strftime('%Y-%m-%d')

    # Build exclude clause safely
    exclude_clause = ""
    if exclude_address:
        clean = exclude_address.replace("'", "''")
        exclude_clause = (
            f" AND LOWER(TRIM(address)) != "
            f"LOWER(TRIM('{clean}'))"
        )

    # Build property type clause for vault (BrightData home_type values)
    vault_type_clause = ""
    if property_types:
        vault_variants = []
        for pt in property_types:
            if pt == "Single Family":
                vault_variants.extend(SINGLE_FAMILY_TYPES)
            elif pt == "Townhouse":
                vault_variants.extend(TOWNHOUSE_TYPES)
            elif pt == "Condo":
                vault_variants.extend(CONDO_TYPES)
            elif pt == "Apartment":
                vault_variants.extend(EXCLUDED_TYPES)
        if vault_variants:
            vt_list = "', '".join(vault_variants)
            vault_type_clause = f" AND home_type IN ('{vt_list}')"

    # Base select - all residential, excludes apartments
    type_list = "', '".join(ALL_RESIDENTIAL_TYPES)
    base = f"""
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
            hdp_url,
            'BRI Vault' as data_source
        FROM properties
        WHERE
            latitude IS NOT NULL
            AND longitude IS NOT NULL
            AND current_price IS NOT NULL
            AND current_price > 0
            AND CAST(latitude AS FLOAT) BETWEEN %s AND %s
            AND CAST(longitude AS FLOAT) BETWEEN %s AND %s
            AND home_type IN ('{type_list}')
            {exclude_clause}
            {vault_type_clause}
    """

    params = (
        bbox['min_lat'], bbox['max_lat'],
        bbox['min_lon'], bbox['max_lon']
    )

    leased_query = base + f"""
            AND listing_status LIKE 'LEASED%%'
            AND last_seen_date >= '{cutoff}'
        LIMIT 500
    """

    active_query = base + """
            AND listing_status LIKE '%%ACTIVE%%'
        LIMIT 500
    """

    leased = []
    active = []

    cursor.execute(leased_query, params)
    columns = [desc[0] for desc in cursor.description]
    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        leased.append(prop)

    cursor.execute(active_query, params)
    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        active.append(prop)

    conn.close()

    # Calculate distances and filter to radius
    result_leased = []
    result_active = []

    for prop in leased:
        try:
            dist = haversine_distance(
                lat, lon,
                float(prop['latitude']),
                float(prop['longitude'])
            )
            if dist <= radius_miles:
                prop['distance_miles'] = round(dist, 3)
                result_leased.append(prop)
        except Exception:
            continue

    for prop in active:
        try:
            dist = haversine_distance(
                lat, lon,
                float(prop['latitude']),
                float(prop['longitude'])
            )
            if dist <= radius_miles:
                prop['distance_miles'] = round(dist, 3)
                result_active.append(prop)
        except Exception:
            continue

    return result_leased, result_active

def fetch_rentcast_properties(lat, lon, radius_miles, months_back,
                              property_types=None):
    """
    Fetch all matching rentcast properties within radius and date window.
    Returns leased and active separately.
    No similarity filtering here — that happens in Python.
    """
    conn = get_connection()
    cursor = conn.cursor()

    bbox = get_bounding_box(lat, lon, radius_miles)
    cutoff = (
        datetime.now() - timedelta(days=months_back * 30.5)
    ).strftime('%Y-%m-%d')

    # Build property type clause for RentCast (property_type field values)
    rc_type_clause = ""
    if property_types:
        rc_types = [
            pt for pt in property_types
            if pt in ('Single Family', 'Townhouse', 'Condo')
        ]
        if rc_types:
            rc_list = "', '".join(rc_types)
            rc_type_clause = f" AND property_type IN ('{rc_list}')"

    base = f"""
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
            NULL as hdp_url,
            'RentCast' as data_source
        FROM rentcast_listings
        WHERE
            latitude IS NOT NULL
            AND longitude IS NOT NULL
            AND price IS NOT NULL
            AND price > 0
            AND CAST(latitude AS FLOAT) BETWEEN %s AND %s
            AND CAST(longitude AS FLOAT) BETWEEN %s AND %s
            AND property_type NOT IN ('Multi-Family', 'Apartment')
            {rc_type_clause}
    """

    params = (
        bbox['min_lat'], bbox['max_lat'],
        bbox['min_lon'], bbox['max_lon']
    )

    leased_query = base + f"""
            AND status = 'Inactive'
            AND last_seen_date >= '{cutoff}'
        LIMIT 500
    """

    active_query = base + """
            AND status = 'Active'
        LIMIT 500
    """

    leased = []
    active = []

    cursor.execute(leased_query, params)
    columns = [desc[0] for desc in cursor.description]
    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        leased.append(prop)

    cursor.execute(active_query, params)
    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        active.append(prop)

    conn.close()

    result_leased = []
    result_active = []

    for prop in leased:
        try:
            dist = haversine_distance(
                lat, lon,
                float(prop['latitude']),
                float(prop['longitude'])
            )
            if dist <= radius_miles:
                prop['distance_miles'] = round(dist, 3)
                result_leased.append(prop)
        except Exception:
            continue

    for prop in active:
        try:
            dist = haversine_distance(
                lat, lon,
                float(prop['latitude']),
                float(prop['longitude'])
            )
            if dist <= radius_miles:
                prop['distance_miles'] = round(dist, 3)
                result_active.append(prop)
        except Exception:
            continue

    return result_leased, result_active

# ============================================================
# FOUR-ROUND APPRAISAL COMP SEARCH
# ============================================================

def run_comp_search(subject, use_rentcast=True, property_types=None):
    """
    Four-round appraisal-method comp search.

    Round 1: 1 mile, 15 months, sqft 15%, beds ±1, same type
    Round 2: 2 miles, 24 months, sqft 15%, beds ±1, same type
    Round 3: 3 miles, 24 months, sqft 15%, beds ±1, all residential
    Round 4: 5 miles, 24 months, sqft 25%, beds ±2, all residential

    Stops when 25+ leased AND 25+ active comps found.
    Returns up to 30 of each, sorted by distance then recency.
    """
    subject_beds = subject.get('bedrooms')
    subject_baths = subject.get('bathrooms')
    subject_sqft = subject.get('living_area')
    subject_type = subject.get('home_type') or subject.get('property_type')
    subject_type_group = get_type_group(subject_type)
    exclude_address = subject.get('address', '')

    print(f"BRI APPRAISAL COMP SEARCH")
    print(f"Subject: {subject.get('address')}, {subject.get('city')}")
    print(f"Type: {subject_type_group} | "
          f"Beds: {subject_beds} | "
          f"Baths: {subject_baths} | "
          f"Sqft: {subject_sqft}")

    rounds = [
        {
            'round': 1,
            'radius': 1.0,
            'months': 15,
            'sqft_tol': 0.20,
            'bed_tol': 1,
            'same_type': False,
            'confidence': 'HIGH'
        },
        {
            'round': 2,
            'radius': 2.0,
            'months': 24,
            'sqft_tol': 0.20,
            'bed_tol': 1,
            'same_type': False,
            'confidence': 'GOOD'
        },
        {
            'round': 3,
            'radius': 3.0,
            'months': 24,
            'sqft_tol': 0.25,
            'bed_tol': 1,
            'same_type': False,
            'confidence': 'MEDIUM'
        },
        {
            'round': 4,
            'radius': 5.0,
            'months': 24,
            'sqft_tol': 0.30,
            'bed_tol': 2,
            'same_type': False,
            'confidence': 'LOW'
        },
    ]

    target = 25
    final_leased = []
    final_active = []
    final_confidence = 'LOW'
    final_round = 4
    final_radius = 5.0

    for r in rounds:
        print(f"[Round {r['round']}] "
              f"Radius: {r['radius']} mi | "
              f"Months: {r['months']} | "
              f"Sqft tol: {int(r['sqft_tol']*100)}% | "
              f"Beds: ±{r['bed_tol']} | "
              f"Same type: {r['same_type']}")

        # Fetch from vault
        vault_leased, vault_active = fetch_vault_properties(
            lat=float(subject['latitude']),
            lon=float(subject['longitude']),
            radius_miles=r['radius'],
            months_back=r['months'],
            exclude_address=exclude_address,
            property_types=property_types
        )

        # Fetch from rentcast
        rc_leased, rc_active = [], []
        if use_rentcast:
            rc_leased, rc_active = fetch_rentcast_properties(
                lat=float(subject['latitude']),
                lon=float(subject['longitude']),
                radius_miles=r['radius'],
                months_back=r['months'],
                property_types=property_types
            )

        # Combine sources
        all_leased = vault_leased + rc_leased
        all_active = vault_active + rc_active

        # Apply similarity filter
        filtered_leased = [
            p for p in all_leased
            if passes_similarity(
                p,
                subject_beds, subject_baths, subject_sqft,
                subject_type_group,
                sqft_tolerance=r['sqft_tol'],
                bed_tolerance=r['bed_tol'],
                same_type_only=r['same_type']
            )
        ]
        filtered_active = [
            p for p in all_active
            if passes_similarity(
                p,
                subject_beds, subject_baths, subject_sqft,
                subject_type_group,
                sqft_tolerance=r['sqft_tol'],
                bed_tolerance=r['bed_tol'],
                same_type_only=r['same_type']
            )
        ]

        print(f"   Leased after filter: {len(filtered_leased)} | "
              f"Active after filter: {len(filtered_active)}")

        # Update best results so far - track the round
        # that produced the most leased comps
        if len(filtered_leased) > len(final_leased):
            final_leased = filtered_leased
            final_confidence = r['confidence']
            final_round = r['round']
            final_radius = r['radius']
        if len(filtered_active) > len(final_active):
            final_active = filtered_active

        # Check stop condition - hit target on both
        if (len(filtered_leased) >= target and
                len(filtered_active) >= target):
            final_confidence = r['confidence']
            final_round = r['round']
            final_radius = r['radius']
            print(f"   Target reached at Round {r['round']} — "
                  f"stopping search")
            break

    # Sort by distance then recency
    def sort_key(p):
        dist = float(p.get('distance_miles') or 99)
        date_str = str(p.get('last_seen_date', '2000-01-01') or
                       '2000-01-01')
        try:
            date_val = datetime.strptime(date_str[:10], '%Y-%m-%d')
            days_ago = (datetime.now() - date_val).days
        except Exception:
            days_ago = 9999
        return (dist, days_ago)

    final_leased.sort(key=sort_key)
    final_active.sort(key=sort_key)

    # Deduplicate by address keeping closest/most recent
    def dedupe(props):
        seen = {}
        for p in props:
            key = str(p.get('address', '') or '').lower().strip()
            if key not in seen:
                seen[key] = p
        return list(seen.values())

    final_leased = dedupe(final_leased)
    final_active = dedupe(final_active)

    print(f"Final: {len(final_leased[:30])} leased | "
          f"{len(final_active[:30])} active | "
          f"Confidence: {final_confidence} | "
          f"Round: {final_round} | "
          f"Radius: {final_radius} mi")

    return {
        'leased': final_leased[:30],
        'active': final_active[:30],
        'confidence': final_confidence,
        'round_stopped': final_round,
        'radius_used': final_radius,
        'total_leased': len(final_leased),
        'total_active': len(final_active),
        'vault_leased_count': len([
            p for p in final_leased
            if p.get('data_source') == 'BRI Vault'
        ]),
        'rentcast_leased_count': len([
            p for p in final_leased
            if p.get('data_source') == 'RentCast'
        ])
    }

# ============================================================
# LEGACY FUNCTIONS - Kept for one-off search compatibility
# ============================================================

def get_nearby_vault_properties(lat, lon, radius_miles=3.0,
                                limit=100, property_types=None,
                                exclude_address=None):
    """Legacy function used by one-off search workflow."""
    leased, active = fetch_vault_properties(
        lat=lat, lon=lon,
        radius_miles=radius_miles,
        months_back=15,
        exclude_address=exclude_address
    )
    combined = leased + active
    combined.sort(key=lambda p: (
        0 if str(p.get('listing_status', '')).startswith('LEASED')
        else 1,
        p.get('distance_miles', 99)
    ))
    return combined[:limit]

def get_nearby_rentcast_properties(lat, lon, radius_miles=3.0,
                                   limit=100, property_types=None):
    """Legacy function used by one-off search workflow."""
    leased, active = fetch_rentcast_properties(
        lat=lat, lon=lon,
        radius_miles=radius_miles,
        months_back=15
    )
    combined = leased + active
    combined.sort(key=lambda p: (
        0 if p.get('listing_status') == 'Inactive' else 1,
        p.get('distance_miles', 99)
    ))
    return combined[:limit]

# ============================================================
# ONE-OFF SEARCH FUNCTIONS
# ============================================================

def save_one_off_search(address, city, state, zipcode,
                        bedrooms, bathrooms, living_area,
                        year_built=None, property_type='Single Family',
                        notes='', requester_name='',
                        latitude=None, longitude=None):
    """Save a one-off property search to Supabase."""
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

# ============================================================
# PROPERTY NOTES
# ============================================================

def save_property_notes(property_id, notes):
    """Save Shannyn's notes for a specific subject property."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE subject_properties
            SET saved_notes = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (notes, property_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error saving notes: {str(e)}")
        return False

def get_property_notes(property_id):
    """Load saved notes for a specific subject property."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT saved_notes
            FROM subject_properties
            WHERE id = %s
        """, (property_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
        return ""
    except Exception as e:
        print(f"Error loading notes: {str(e)}")
        return ""

# ============================================================
# ANALYSIS REPORTS
# ============================================================

def save_analysis_report(property_id, property_address,
                         property_city, report_text,
                         selected_comps, vault_leased_count,
                         rentcast_leased_count, total_leased_count,
                         total_active_count, radius_used,
                         property_notes):
    """Save a completed analysis report to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO analysis_reports (
                property_id, property_address, property_city,
                report_text, comps_used,
                vault_leased_count, rentcast_leased_count,
                total_leased_count, total_active_count,
                radius_used, property_notes
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            RETURNING id
        """, (
            property_id,
            property_address,
            property_city,
            report_text,
            json.dumps(selected_comps),
            vault_leased_count,
            rentcast_leased_count,
            total_leased_count,
            total_active_count,
            radius_used,
            property_notes
        ))
        report_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return report_id
    except Exception as e:
        print(f"Error saving report: {str(e)}")
        return None

def get_reports_for_property(property_id, limit=10):
    """Load previous analysis reports for a subject property."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id,
                report_text,
                vault_leased_count,
                rentcast_leased_count,
                total_leased_count,
                total_active_count,
                radius_used,
                property_notes,
                TO_CHAR(created_at,
                    'Month DD, YYYY HH12:MI AM') as created_at
            FROM analysis_reports
            WHERE property_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (property_id, limit))
        columns = [desc[0] for desc in cursor.description]
        results = []
        for row in cursor.fetchall():
            report = {col: clean_value(val)
                      for col, val in zip(columns, row)}
            results.append(report)
        conn.close()
        return results
    except Exception as e:
        print(f"Error loading reports: {str(e)}")
        return []

# ============================================================
# MANUAL ADDRESS LOOKUP
# ============================================================

def lookup_property_by_address(search_text):
    """
    Search the properties table for an address match.
    Case-insensitive partial match on the address column.
    Returns the first matching property dict, or None.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT address, city, state, zipcode,
               bedrooms, bathrooms, current_price, home_type
        FROM properties
        WHERE address ILIKE %s
        LIMIT 1
    """, (f"%{search_text}%",))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    columns = ['address', 'city', 'state', 'zipcode',
               'bedrooms', 'bathrooms', 'current_price', 'home_type']
    return {col: clean_value(val) for col, val in zip(columns, row)}

# ============================================================
# SUBJECT PROPERTIES AND STATS
# ============================================================

def get_subject_properties():
    """Get all of Shannyn's subject properties with coordinates."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, address, city, state, bedrooms, bathrooms,
               living_area, latitude, longitude,
               current_rent, notes, saved_notes
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

    cursor.execute("SELECT COUNT(*) FROM analysis_reports")
    reports = cursor.fetchone()

    conn.close()

    return {
        'vault_total': vault[0],
        'vault_leased': vault[1],
        'vault_active': vault[2],
        'rentcast_total': rc[0],
        'rentcast_leased': rc[1],
        'rentcast_active': rc[2],
        'rentcast_last_dump': rc[3],
        'one_off_total': one_off[0],
        'reports_total': reports[0]
    }
