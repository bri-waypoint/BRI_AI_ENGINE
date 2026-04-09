# scripts/rentcast_dump.py
# BRI RentCast Bi-Weekly Data Dump
# Pulls active + leased listings for all Boise area ZIP codes
# Stores in Supabase rentcast_listings table
# Run every Sunday and Wednesday at 10PM via Windows Task Scheduler

import os
import sys
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# ============================================================
# CONFIGURATION
# ============================================================

# Boise area ZIP codes to pull data for
BOISE_ZIP_CODES = [
    '83702',  # Boise - North End, Downtown
    '83703',  # Boise - Garden City, Northwest
    '83704',  # Boise - West Boise
    '83705',  # Boise - Southeast
    '83706',  # Boise - Southeast, Boise State area
    '83709',  # Boise - Southwest
    '83712',  # Boise - East End, Warm Springs
    '83713',  # Boise - West, Meridian border
    '83714',  # Garden City, North Boise
    '83716',  # Boise - Southeast, Barber Valley
    '83642',  # Meridian
    '83616',  # Eagle
    '83634',  # Kuna
    '83669',  # Star
]

# Property types to pull (RentCast format - case sensitive!)
PROPERTY_TYPES = "Single Family|Townhouse|Condo|Multi-Family"

# RentCast API settings
RENTCAST_BASE_URL = "https://api.rentcast.io/v1"
RENTCAST_API_KEY = os.getenv('RENTCAST_API_KEY')

# Supabase connection settings
SUPABASE_CONFIG = {
    'host': os.getenv('SUPABASE_HOST'),
    'database': os.getenv('SUPABASE_DB'),
    'user': os.getenv('SUPABASE_USER'),
    'password': os.getenv('SUPABASE_PASSWORD'),
    'port': int(os.getenv('SUPABASE_PORT', 5432)),
    'sslmode': 'require',
    'connect_timeout': 30
}

# ============================================================
# RENTCAST API FUNCTIONS
# ============================================================

def get_rentcast_headers():
    """Get RentCast API headers."""
    return {
        "accept": "application/json",
        "X-Api-Key": RENTCAST_API_KEY
    }

def fetch_listings_by_zip(zip_code, status="Active", limit=100):
    """
    Fetch rental listings for a specific ZIP code from RentCast.
    
    Args:
        zip_code: 5-digit ZIP code
        status: 'Active' or 'Inactive' (leased)
        limit: Max results (up to 500)
    
    Returns:
        List of listing dictionaries or empty list on error
    """
    params = {
        "zipCode": zip_code,
        "status": status,
        "propertyType": PROPERTY_TYPES,
        "limit": limit
    }

    try:
        response = requests.get(
            f"{RENTCAST_BASE_URL}/listings/rental/long-term",
            headers=get_rentcast_headers(),
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            listings = response.json()
            return listings if isinstance(listings, list) else []
        elif response.status_code == 401:
            print(f"    ERROR: Invalid API key - check RENTCAST_API_KEY in .env")
            return []
        elif response.status_code == 429:
            print(f"    ERROR: Rate limit exceeded - too many API calls")
            return []
        elif response.status_code == 404:
            print(f"    No listings found for ZIP {zip_code} (status={status})")
            return []
        else:
            print(f"    ERROR: {response.status_code} - {response.text[:100]}")
            return []

    except requests.Timeout:
        print(f"    TIMEOUT: ZIP {zip_code} took too long")
        return []
    except Exception as e:
        print(f"    EXCEPTION: {str(e)}")
        return []

# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def get_db_connection():
    """Get Supabase PostgreSQL connection."""
    return psycopg2.connect(**SUPABASE_CONFIG)

def upsert_listings(conn, listings, dump_date, status):
    """
    Upsert listings into rentcast_listings table.
    Uses ON CONFLICT to update existing records.
    
    Args:
        conn: Database connection
        listings: List of RentCast listing dictionaries
        dump_date: Date string for this dump (YYYY-MM-DD)
        status: 'Active' or 'Leased'
    
    Returns:
        Number of records upserted
    """
    if not listings:
        return 0

    cursor = conn.cursor()
    upserted = 0

    for listing in listings:
        # Get listing ID (RentCast's unique identifier)
        listing_id = listing.get('id', '')
        if not listing_id:
            continue

        # Get last seen date safely
        last_seen = listing.get('lastSeenDate', '')
        if last_seen and len(last_seen) >= 10:
            last_seen = last_seen[:10]

        # Get listed date safely
        listed_date = listing.get('listedDate', '')
        if listed_date and len(listed_date) >= 10:
            listed_date = listed_date[:10]

        # Get removed date safely
        removed_date = listing.get('removedDate', '')
        if removed_date and len(removed_date) >= 10:
            removed_date = removed_date[:10]

        try:
            cursor.execute("""
                INSERT INTO rentcast_listings (
                    id, formatted_address, address_line1, address_line2,
                    city, state, zip_code, county,
                    latitude, longitude,
                    property_type, bedrooms, bathrooms,
                    square_footage, lot_size, year_built,
                    status, price, listing_type,
                    listed_date, removed_date, last_seen_date,
                    days_on_market, mls_name, mls_number,
                    dump_date, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    price = EXCLUDED.price,
                    last_seen_date = EXCLUDED.last_seen_date,
                    removed_date = EXCLUDED.removed_date,
                    days_on_market = EXCLUDED.days_on_market,
                    dump_date = EXCLUDED.dump_date,
                    updated_at = NOW()
            """, (
                listing_id,
                listing.get('formattedAddress', ''),
                listing.get('addressLine1', ''),
                listing.get('addressLine2', ''),
                listing.get('city', ''),
                listing.get('state', ''),
                listing.get('zipCode', ''),
                listing.get('county', ''),
                listing.get('latitude'),
                listing.get('longitude'),
                listing.get('propertyType', ''),
                listing.get('bedrooms'),
                listing.get('bathrooms'),
                listing.get('squareFootage'),
                listing.get('lotSize'),
                listing.get('yearBuilt'),
                status,
                listing.get('price'),
                listing.get('listingType', ''),
                listed_date or None,
                removed_date or None,
                last_seen or None,
                listing.get('daysOnMarket'),
                listing.get('mlsName', ''),
                listing.get('mlsNumber', ''),
                dump_date
            ))
            upserted += 1

        except Exception as e:
            print(f"    DB Error for {listing_id}: {str(e)[:100]}")
            conn.rollback()
            continue

    conn.commit()
    cursor.close()
    return upserted

def get_table_stats(conn):
    """Get current stats from rentcast_listings table."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN status = 'Active' THEN 1 END) as active,
            COUNT(CASE WHEN status = 'Inactive' THEN 1 END) as inactive,
            MAX(dump_date) as last_dump
        FROM rentcast_listings
    """)
    row = cursor.fetchone()
    cursor.close()
    return {
        'total': row[0],
        'active': row[1],
        'inactive': row[2],
        'last_dump': row[3]
    }

# ============================================================
# MAIN DUMP FUNCTION
# ============================================================

def run_rentcast_dump():
    """
    Main function: Pull all RentCast data for Boise area ZIP codes
    and store in Supabase.
    """
    start_time = datetime.now()
    dump_date = start_time.strftime('%Y-%m-%d')

    print("=" * 70)
    print("BRI RENTCAST BI-WEEKLY DATA DUMP")
    print("=" * 70)
    print(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Dump date: {dump_date}")
    print(f"ZIP codes: {len(BOISE_ZIP_CODES)}")
    print(f"API Key: {RENTCAST_API_KEY[:20]}..." if RENTCAST_API_KEY else "NO API KEY!")
    print("=" * 70)

    if not RENTCAST_API_KEY:
        print("ERROR: RENTCAST_API_KEY not found in .env file!")
        return False

    # Connect to Supabase
    print("\n[1] Connecting to Supabase...")
    try:
        conn = get_db_connection()
        print("    Connected successfully!")
    except Exception as e:
        print(f"    CONNECTION FAILED: {str(e)}")
        return False

    # Track totals
    total_active = 0
    total_leased = 0
    total_api_calls = 0
    zip_results = []

    # Process each ZIP code
    print(f"\n[2] Processing {len(BOISE_ZIP_CODES)} ZIP codes...")
    print("-" * 70)

    for i, zip_code in enumerate(BOISE_ZIP_CODES, 1):
        print(f"\n  ZIP {zip_code} ({i}/{len(BOISE_ZIP_CODES)}):")

        # Fetch ACTIVE listings
        print(f"    Fetching active listings...")
        active_listings = fetch_listings_by_zip(
            zip_code=zip_code,
            status="Active",
            limit=100
        )
        total_api_calls += 1
        print(f"    Found {len(active_listings)} active listings")

        # Upsert active listings
        active_upserted = upsert_listings(
            conn, active_listings, dump_date, "Active"
        )
        print(f"    Saved {active_upserted} active listings to Supabase")

        # Fetch INACTIVE (leased) listings
        print(f"    Fetching leased listings...")
        leased_listings = fetch_listings_by_zip(
            zip_code=zip_code,
            status="Inactive",
            limit=100
        )
        total_api_calls += 1
        print(f"    Found {len(leased_listings)} leased listings")

        # Upsert leased listings
        leased_upserted = upsert_listings(
            conn, leased_listings, dump_date, "Inactive"
        )
        print(f"    Saved {leased_upserted} leased listings to Supabase")

        # Track results
        total_active += active_upserted
        total_leased += leased_upserted
        zip_results.append({
            'zip': zip_code,
            'active': active_upserted,
            'leased': leased_upserted
        })

    # Get final table stats
    print("\n[3] Getting final table statistics...")
    stats = get_table_stats(conn)
    conn.close()

    # Summary report
    end_time = datetime.now()
    duration = (end_time - start_time).seconds

    print("\n" + "=" * 70)
    print("DUMP COMPLETE - SUMMARY REPORT")
    print("=" * 70)
    print(f"\nDump Date: {dump_date}")
    print(f"Duration: {duration} seconds")
    print(f"Total API Calls Used: {total_api_calls}")
    print(f"\nThis Dump:")
    print(f"  Active listings saved: {total_active}")
    print(f"  Leased listings saved: {total_leased}")
    print(f"  Total saved: {total_active + total_leased}")
    print(f"\nDatabase Totals:")
    print(f"  Total records: {stats['total']:,}")
    print(f"  Active listings: {stats['active']:,}")
    print(f"  Leased listings: {stats['inactive']:,}")
    print(f"  Last dump date: {stats['last_dump']}")
    print(f"\nZIP Code Breakdown:")
    print(f"  {'ZIP':<10} {'Active':<10} {'Leased':<10} {'Total':<10}")
    print(f"  {'-'*40}")
    for r in zip_results:
        total = r['active'] + r['leased']
        print(f"  {r['zip']:<10} {r['active']:<10} {r['leased']:<10} {total:<10}")
    print("=" * 70)
    print("BRI RentCast dump completed successfully!")
    print("=" * 70)

    return True

# ============================================================
# RUN THE DUMP
# ============================================================

if __name__ == "__main__":
    success = run_rentcast_dump()
    sys.exit(0 if success else 1)