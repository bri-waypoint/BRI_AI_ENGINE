# scripts/geocode_subjects.py
# Automatically geocode subject properties missing lat/lon
# Uses OpenStreetMap Nominatim (FREE - no API key needed!)
# Updates Supabase directly

import os
import sys
import time
import requests
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Supabase connection
SUPABASE_CONFIG = {
    'host': os.getenv('SUPABASE_HOST'),
    'database': os.getenv('SUPABASE_DB'),
    'user': os.getenv('SUPABASE_USER'),
    'password': os.getenv('SUPABASE_PASSWORD'),
    'port': int(os.getenv('SUPABASE_PORT', 5432)),
    'sslmode': 'require',
    'connect_timeout': 30
}

def get_connection():
    """Get Supabase connection."""
    return psycopg2.connect(**SUPABASE_CONFIG)

def geocode_address(address, city, state):
    """
    Geocode an address using OpenStreetMap Nominatim (FREE).
    Returns (latitude, longitude) or (None, None) if not found.
    """
    # Build full address string
    full_address = f"{address}, {city}, {state}, USA"

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
                return lat, lon
            else:
                # Try without street number
                parts = address.split(' ', 1)
                if len(parts) > 1:
                    street_only = parts[1]
                    simplified = f"{street_only}, {city}, {state}, USA"
                    params["q"] = simplified
                    response2 = requests.get(
                        url, params=params,
                        headers=headers,
                        timeout=10
                    )
                    if response2.status_code == 200:
                        results2 = response2.json()
                        if results2:
                            lat = float(results2[0]['lat'])
                            lon = float(results2[0]['lon'])
                            print(f"      (Found via street name only)")
                            return lat, lon
                return None, None
        else:
            print(f"      Geocoding error: {response.status_code}")
            return None, None

    except Exception as e:
        print(f"      Geocoding exception: {str(e)}")
        return None, None

def update_coordinates(conn, property_id, lat, lon):
    """Update lat/lon for a subject property in Supabase."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE subject_properties
        SET latitude = %s, longitude = %s
        WHERE id = %s
    """, (lat, lon, property_id))
    conn.commit()
    cursor.close()

def run_geocoding():
    """Main geocoding function."""
    print("=" * 70)
    print("BRI SUBJECT PROPERTY GEOCODER")
    print("=" * 70)
    print("Using OpenStreetMap Nominatim (FREE)")
    print()

    # Connect to Supabase
    print("[1] Connecting to Supabase...")
    try:
        conn = get_connection()
        print("    Connected!")
    except Exception as e:
        print(f"    FAILED: {str(e)}")
        return

    # Get properties missing coordinates
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, address, city, state
        FROM subject_properties
        WHERE latitude IS NULL OR longitude IS NULL
        ORDER BY address
    """)
    missing = cursor.fetchall()
    cursor.close()

    print(f"\n[2] Found {len(missing)} properties missing coordinates:")
    print()

    if not missing:
        print("    All properties already have coordinates!")
        conn.close()
        return

    # Show all missing properties
    for i, (pid, addr, city, state) in enumerate(missing, 1):
        print(f"    {i:2}. ID {pid}: {addr}, {city}, {state}")

    print()
    print("[3] Starting geocoding...")
    print("    (1 second delay between calls to respect API limits)")
    print()

    # Track results
    success = []
    failed = []

    for i, (property_id, address, city, state) in enumerate(missing, 1):
        print(f"  [{i}/{len(missing)}] {address}, {city}, {state}")

        # Geocode the address
        lat, lon = geocode_address(address, city, state)

        if lat and lon:
            # Validate coordinates are in Idaho/Treasure Valley area
            # Idaho lat: 42-49, lon: -117 to -111
            if 42.0 <= lat <= 49.0 and -117.5 <= lon <= -111.0:
                update_coordinates(conn, property_id, lat, lon)
                print(f"      ✅ Found: lat={lat:.4f}, lon={lon:.4f}")
                success.append({
                    'id': property_id,
                    'address': address,
                    'city': city,
                    'lat': lat,
                    'lon': lon
                })
            else:
                print(f"      ⚠️  Coordinates outside Idaho: "
                      f"lat={lat:.4f}, lon={lon:.4f} - SKIPPED")
                failed.append({
                    'id': property_id,
                    'address': address,
                    'city': city,
                    'reason': f'Outside Idaho: {lat:.4f}, {lon:.4f}'
                })
        else:
            print(f"      ❌ Not found - needs manual entry")
            failed.append({
                'id': property_id,
                'address': address,
                'city': city,
                'reason': 'Address not found'
            })

        # Respect API rate limits (1 request per second)
        if i < len(missing):
            time.sleep(1.0)

    conn.close()

    # Summary report
    print()
    print("=" * 70)
    print("GEOCODING COMPLETE - SUMMARY")
    print("=" * 70)
    print(f"\n✅ Successfully geocoded: {len(success)} properties")
    print(f"❌ Failed/needs manual entry: {len(failed)} properties")

    if success:
        print(f"\nSUCCESSFULLY GEOCODED:")
        for s in success:
            print(f"  ID {s['id']}: {s['address']}, {s['city']}")
            print(f"           lat={s['lat']:.4f}, lon={s['lon']:.4f}")

    if failed:
        print(f"\nNEEDS MANUAL ENTRY:")
        for f in failed:
            print(f"  ID {f['id']}: {f['address']}, {f['city']}")
            print(f"           Reason: {f['reason']}")

    print()
    print("=" * 70)
    print("Next steps:")
    print("1. Check the successfully geocoded properties above")
    print("2. Manually add coordinates for any that failed")
    print("3. Run BRI AI Engine - more properties will now appear!")
    print("=" * 70)

if __name__ == "__main__":
    run_geocoding()