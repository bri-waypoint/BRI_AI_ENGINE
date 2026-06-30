# scripts/rentcast_dump.py
# BRI RentCast Bi-Weekly Data Dump
# Fixed: Reconnects to database for each ZIP to prevent timeout
# Pulls ONLY leased (Inactive) listings for all Boise area ZIP codes

import os
import sys
import requests
import psycopg2
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(__file__)), '.env'
))

# ============================================================
# CONFIGURATION
# ============================================================

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

PROPERTY_TYPES = "Single Family|Townhouse|Condo|Multi-Family"
RESULTS_LIMIT = 500
RENTCAST_BASE_URL = "https://api.rentcast.io/v1"
RENTCAST_API_KEY = os.getenv('RENTCAST_API_KEY')

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
# SMS NOTIFICATION
# ============================================================

def send_sms(message):
    """Send SMS via Gmail to Verizon number."""
    try:
        gmail_password = os.getenv('GMAIL_APP_PASSWORD')
        if not gmail_password:
            print(f"SMS skipped - no GMAIL_APP_PASSWORD")
            return False
        msg = MIMEText(message)
        msg['From'] = 'markflory1@gmail.com'
        msg['To'] = '2088670377@vtext.com'
        msg['Subject'] = ''
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login('markflory1@gmail.com', gmail_password)
            server.send_message(msg)
        print(f"SMS sent: {message}")
        return True
    except Exception as e:
        print(f"SMS failed: {str(e)}")
        return False

# ============================================================
# RENTCAST API FUNCTIONS
# ============================================================

def get_headers():
    return {
        "accept": "application/json",
        "X-Api-Key": RENTCAST_API_KEY
    }

def fetch_leased_listings(zip_code, limit=500, offset=0):
    """Fetch leased listings for a ZIP code with pagination."""
    params = {
        "zipCode": zip_code,
        "status": "Inactive",
        "propertyType": PROPERTY_TYPES,
        "limit": limit,
        "offset": offset
    }

    try:
        response = requests.get(
            f"{RENTCAST_BASE_URL}/listings/rental/long-term",
            headers=get_headers(),
            params=params,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, list) else []
        elif response.status_code == 401:
            print(f"    ERROR: Invalid API key!")
            return []
        elif response.status_code == 429:
            print(f"    ERROR: Rate limit exceeded!")
            return []
        else:
            print(f"    ERROR: {response.status_code}")
            return []

    except requests.Timeout:
        print(f"    TIMEOUT for ZIP {zip_code}")
        return []
    except Exception as e:
        print(f"    EXCEPTION: {str(e)}")
        return []

def fetch_all_leased_with_pagination(zip_code):
    """Fetch ALL leased listings using pagination."""
    all_listings = []
    offset = 0
    page = 1

    while True:
        print(f"    Page {page} (offset={offset})...")
        listings = fetch_leased_listings(
            zip_code=zip_code,
            limit=RESULTS_LIMIT,
            offset=offset
        )

        if not listings:
            break

        all_listings.extend(listings)
        print(f"    Got {len(listings)} records "
              f"(total so far: {len(all_listings)})")

        if len(listings) < RESULTS_LIMIT:
            break

        offset += RESULTS_LIMIT
        page += 1

        if page > 10:
            print(f"    Reached max pages for ZIP {zip_code}")
            break

    return all_listings

# ============================================================
# DATABASE FUNCTIONS - Reconnect for each ZIP!
# ============================================================

def get_fresh_connection():
    """
    Get a FRESH database connection.
    Called for each ZIP code to prevent timeout issues.
    """
    return psycopg2.connect(**SUPABASE_CONFIG)

def upsert_listings_with_reconnect(listings, dump_date):
    """
    Upsert listings with a fresh connection per batch.
    Reconnects every 100 records to prevent timeout.
    Returns (inserted, updated) counts.
    """
    if not listings:
        return 0, 0

    inserted = 0
    updated = 0
    batch_size = 100  # Reconnect every 100 records

    for batch_start in range(0, len(listings), batch_size):
        batch = listings[batch_start:batch_start + batch_size]

        # Fresh connection for each batch
        try:
            conn = get_fresh_connection()
            cursor = conn.cursor()
        except Exception as e:
            print(f"    Connection failed: {str(e)}")
            continue

        for listing in batch:
            listing_id = listing.get('id', '')
            if not listing_id:
                continue

            # Safely extract dates
            last_seen = listing.get('lastSeenDate', '')
            last_seen = last_seen[:10] if last_seen and len(last_seen) >= 10 else None

            listed_date = listing.get('listedDate', '')
            listed_date = listed_date[:10] if listed_date and len(listed_date) >= 10 else None

            removed_date = listing.get('removedDate', '')
            removed_date = removed_date[:10] if removed_date and len(removed_date) >= 10 else None

            try:
                # Check if exists
                cursor.execute(
                    "SELECT id FROM rentcast_listings WHERE id = %s",
                    (listing_id,)
                )
                exists = cursor.fetchone()

                cursor.execute("""
                    INSERT INTO rentcast_listings (
                        id, formatted_address, address_line1,
                        address_line2, city, state, zip_code,
                        county, latitude, longitude,
                        property_type, bedrooms, bathrooms,
                        square_footage, lot_size, year_built,
                        status, price, listing_type,
                        listed_date, removed_date, last_seen_date,
                        days_on_market, mls_name, mls_number,
                        dump_date, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, NOW()
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
                    'Inactive',
                    listing.get('price'),
                    listing.get('listingType', ''),
                    listed_date,
                    removed_date,
                    last_seen,
                    listing.get('daysOnMarket'),
                    listing.get('mlsName', ''),
                    listing.get('mlsNumber', ''),
                    dump_date
                ))

                if exists:
                    updated += 1
                else:
                    inserted += 1

            except Exception as e:
                print(f"    DB Error for {listing_id}: "
                      f"{str(e)[:60]}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

        # Commit and close this batch connection
        try:
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"    Commit error: {str(e)[:60]}")

        print(f"    Batch {batch_start//batch_size + 1} saved "
              f"({min(batch_start + batch_size, len(listings))}"
              f"/{len(listings)} records)")

    return inserted, updated

def get_table_stats():
    """Get current stats - uses fresh connection."""
    try:
        conn = get_fresh_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN status = 'Active'
                      THEN 1 END) as active,
                COUNT(CASE WHEN status = 'Inactive'
                      THEN 1 END) as leased,
                MAX(dump_date) as last_dump
            FROM rentcast_listings
        """)
        row = cursor.fetchone()
        conn.close()
        return {
            'total': row[0],
            'active': row[1],
            'leased': row[2],
            'last_dump': row[3]
        }
    except Exception as e:
        print(f"Stats error: {str(e)}")
        return {'total': 0, 'active': 0, 'leased': 0, 'last_dump': None}

# ============================================================
# MAIN DUMP FUNCTION
# ============================================================

def run_rentcast_dump():
    """
    Main function: Pull all RentCast leased data for Boise area.
    Uses fresh database connection per ZIP to prevent timeouts.
    """
    start_time = datetime.now()
    dump_date = start_time.strftime('%Y-%m-%d')

    print("=" * 70)
    print("BRI RENTCAST LEASED PROPERTY DUMP")
    print("=" * 70)
    print(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Dump date: {dump_date}")
    print(f"ZIP codes: {len(BOISE_ZIP_CODES)}")
    print(f"Results per page: {RESULTS_LIMIT}")
    print(f"Status: Inactive (Leased) ONLY")
    print(f"Connection: Fresh per ZIP (prevents timeout!)")
    print("=" * 70)

    if not RENTCAST_API_KEY:
        print("ERROR: RENTCAST_API_KEY not found in .env!")
        send_sms("BRI RentCast FAILED - No API key found")
        return False

    # Get starting stats
    print("\n[1] Getting current database stats...")
    before_stats = get_table_stats()
    print(f"    Current leased records: {before_stats['leased']:,}")

    # Track totals
    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    total_api_calls = 0
    zip_results = []

    print(f"\n[2] Processing {len(BOISE_ZIP_CODES)} ZIP codes...")
    print("-" * 70)

    try:
        for i, zip_code in enumerate(BOISE_ZIP_CODES, 1):
            print(f"\n  ZIP {zip_code} ({i}/{len(BOISE_ZIP_CODES)}):")

            # Fetch listings from RentCast
            listings = fetch_all_leased_with_pagination(zip_code)
            pages = max(1, (len(listings) // RESULTS_LIMIT) + 1)
            total_api_calls += pages

            print(f"    Total fetched: {len(listings)} leased listings")

            # Save with fresh connection per batch
            if listings:
                inserted, updated = upsert_listings_with_reconnect(
                    listings, dump_date
                )
                print(f"    Saved: {inserted} new, {updated} updated")
            else:
                inserted, updated = 0, 0
                print(f"    No listings to save")

            total_fetched += len(listings)
            total_inserted += inserted
            total_updated += updated

            zip_results.append({
                'zip': zip_code,
                'fetched': len(listings),
                'inserted': inserted,
                'updated': updated
            })

        # Final stats
        print("\n[3] Getting final statistics...")
        after_stats = get_table_stats()

        end_time = datetime.now()
        duration = (end_time - start_time).seconds

        print("\n" + "=" * 70)
        print("DUMP COMPLETE - SUMMARY REPORT")
        print("=" * 70)
        print(f"\nDump Date: {dump_date}")
        print(f"Duration: {duration} seconds")
        print(f"API Calls Used: {total_api_calls}")
        print(f"\nThis Dump:")
        print(f"  Records fetched: {total_fetched:,}")
        print(f"  New records: {total_inserted:,}")
        print(f"  Updated records: {total_updated:,}")
        print(f"\nDatabase Totals:")
        print(f"  Total leased records: {after_stats['leased']:,}")
        print(f"  Previous count: {before_stats['leased']:,}")
        net_new = after_stats['leased'] - before_stats['leased']
        print(f"  Net new records: {net_new:,}")
        print(f"\nZIP Code Breakdown:")
        print(f"  {'ZIP':<10} {'Fetched':<10} {'New':<10} {'Updated':<10}")
        print(f"  {'-'*42}")
        for r in zip_results:
            print(f"  {r['zip']:<10} {r['fetched']:<10} "
                  f"{r['inserted']:<10} {r['updated']:<10}")
        print("=" * 70)
        print("RentCast dump completed successfully!")
        print(f"Total leased comps available: {after_stats['leased']:,}")
        print("=" * 70)

        send_sms(
            f"BRI RentCast Done! "
            f"{total_fetched:,} fetched, "
            f"{total_inserted:,} new, "
            f"{total_updated:,} updated. "
            f"Total leased: {after_stats['leased']:,}"
        )
        return True

    except Exception as e:
        print(f"FATAL ERROR: {str(e)}")
        send_sms(f"BRI RentCast FAILED - {str(e)[:80]}")
        return False

if __name__ == "__main__":
    success = run_rentcast_dump()
    sys.exit(0 if success else 1)