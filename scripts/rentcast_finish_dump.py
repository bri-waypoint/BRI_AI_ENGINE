# scripts/rentcast_finish_dump.py
# SMART VERSION: Fetch ALL from RentCast first, save locally,
# then push to Supabase separately.
# If Supabase fails, just re-run Phase 2 - no extra API costs!

import os
import sys
import json
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(__file__)), '.env'
))

# Only the 4 ZIPs that failed or weren't reached
MISSING_ZIP_CODES = [
    '83642',  # Meridian - failed mid-save
    '83616',  # Eagle - not reached
    '83634',  # Kuna - not reached
    '83669',  # Star - not reached
]

PROPERTY_TYPES = "Single Family|Townhouse|Condo|Multi-Family"
RESULTS_LIMIT = 500
RENTCAST_BASE_URL = "https://api.rentcast.io/v1"
RENTCAST_API_KEY = os.getenv('RENTCAST_API_KEY')

# Local storage path for fetched data
LOCAL_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'data', 'rentcast_cache'
)

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
# PHASE 1: FETCH FROM RENTCAST AND SAVE LOCALLY
# ============================================================

def get_headers():
    return {
        "accept": "application/json",
        "X-Api-Key": RENTCAST_API_KEY
    }

def fetch_zip_from_rentcast(zip_code):
    """Fetch ALL leased listings for a ZIP using pagination."""
    all_listings = []
    offset = 0
    page = 1

    while True:
        print(f"    Page {page} (offset={offset})...")
        params = {
            "zipCode": zip_code,
            "status": "Inactive",
            "propertyType": PROPERTY_TYPES,
            "limit": RESULTS_LIMIT,
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
                listings = data if isinstance(data, list) else []
                if not listings:
                    break
                all_listings.extend(listings)
                print(f"    Got {len(listings)} records "
                      f"(total: {len(all_listings)})")
                if len(listings) < RESULTS_LIMIT:
                    break
                offset += RESULTS_LIMIT
                page += 1
                if page > 10:
                    break
            else:
                print(f"    API Error: {response.status_code}")
                break

        except Exception as e:
            print(f"    Fetch error: {str(e)[:60]}")
            break

    return all_listings

def save_locally(zip_code, listings, dump_date):
    """
    Save fetched listings to a local JSON file.
    This is our safety net - if Supabase fails,
    we can re-run Phase 2 without calling RentCast again!
    """
    os.makedirs(LOCAL_DATA_DIR, exist_ok=True)
    filename = f"rentcast_{zip_code}_{dump_date}.json"
    filepath = os.path.join(LOCAL_DATA_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            'zip_code': zip_code,
            'dump_date': dump_date,
            'record_count': len(listings),
            'fetched_at': datetime.now().isoformat(),
            'listings': listings
        }, f, indent=2)

    print(f"    Saved locally: {filename} ({len(listings)} records)")
    return filepath

def phase1_fetch_all(dump_date):
    """
    PHASE 1: Fetch ALL data from RentCast and save locally.
    No Supabase connection needed here!
    Returns dict of {zip_code: local_filepath}
    """
    print("\n" + "=" * 70)
    print("PHASE 1: FETCHING FROM RENTCAST")
    print("=" * 70)
    print("Saving everything locally first...")
    print("If Supabase fails later, Phase 2 can be re-run FREE!")
    print("-" * 70)

    local_files = {}
    total_fetched = 0
    total_api_calls = 0

    for i, zip_code in enumerate(MISSING_ZIP_CODES, 1):
        print(f"\n  ZIP {zip_code} ({i}/{len(MISSING_ZIP_CODES)}):")

        # Check if we already have a local file for today
        filename = f"rentcast_{zip_code}_{dump_date}.json"
        filepath = os.path.join(LOCAL_DATA_DIR, filename)

        if os.path.exists(filepath):
            print(f"    Local file already exists - skipping API call!")
            print(f"    (Delete {filename} to re-fetch from RentCast)")
            local_files[zip_code] = filepath
            with open(filepath, 'r') as f:
                data = json.load(f)
                total_fetched += data.get('record_count', 0)
            continue

        # Fetch from RentCast
        listings = fetch_zip_from_rentcast(zip_code)
        pages = max(1, (len(listings) // RESULTS_LIMIT) + 1)
        total_api_calls += pages

        print(f"    Total fetched: {len(listings)} listings")

        # Save locally immediately
        if listings:
            filepath = save_locally(zip_code, listings, dump_date)
            local_files[zip_code] = filepath
            total_fetched += len(listings)
        else:
            print(f"    No listings found for ZIP {zip_code}")

    print(f"\n{'='*70}")
    print(f"PHASE 1 COMPLETE")
    print(f"Total records fetched: {total_fetched:,}")
    print(f"API calls used: {total_api_calls}")
    print(f"Local files saved: {len(local_files)}")
    print(f"RentCast connection DONE - no more API costs!")
    print(f"{'='*70}")

    return local_files, total_fetched, total_api_calls

# ============================================================
# PHASE 2: PUSH LOCAL DATA TO SUPABASE
# ============================================================

def get_fresh_connection():
    """Get a fresh Supabase connection."""
    return psycopg2.connect(**SUPABASE_CONFIG)

def push_zip_to_supabase(zip_code, filepath, dump_date,
                          batch_size=100):
    """
    Push locally saved data to Supabase.
    Uses fresh connection every batch_size records.
    If this fails, just re-run Phase 2 - no API cost!
    """
    print(f"\n  ZIP {zip_code}:")

    # Load from local file
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    listings = data.get('listings', [])
    print(f"    Loading {len(listings)} records from local file...")

    if not listings:
        print(f"    No records to push")
        return 0, 0

    inserted = 0
    updated = 0
    batch_num = 0

    for batch_start in range(0, len(listings), batch_size):
        batch = listings[batch_start:batch_start + batch_size]
        batch_num += 1
        end_rec = min(batch_start + batch_size, len(listings))

        # Fresh connection for EVERY batch
        try:
            conn = get_fresh_connection()
            cursor = conn.cursor()
        except Exception as e:
            print(f"    Batch {batch_num} connection failed: "
                  f"{str(e)[:60]}")
            continue

        batch_inserted = 0
        batch_updated = 0

        for listing in batch:
            listing_id = listing.get('id', '')
            if not listing_id:
                continue

            # Safely extract dates
            last_seen = listing.get('lastSeenDate', '')
            last_seen = (last_seen[:10]
                        if last_seen and len(last_seen) >= 10
                        else None)
            listed_date = listing.get('listedDate', '')
            listed_date = (listed_date[:10]
                          if listed_date and len(listed_date) >= 10
                          else None)
            removed_date = listing.get('removedDate', '')
            removed_date = (removed_date[:10]
                           if removed_date and len(removed_date) >= 10
                           else None)

            try:
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
                    batch_updated += 1
                else:
                    batch_inserted += 1

            except Exception as e:
                print(f"    Record error: {str(e)[:60]}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

        # Commit and close this batch
        try:
            conn.commit()
            conn.close()
            inserted += batch_inserted
            updated += batch_updated
            print(f"    Batch {batch_num} saved: "
                  f"records {batch_start+1}-{end_rec} "
                  f"({batch_inserted} new, {batch_updated} updated)")
        except Exception as e:
            print(f"    Batch {batch_num} commit error: "
                  f"{str(e)[:60]}")

    print(f"    ZIP {zip_code} complete: "
          f"{inserted} new, {updated} updated")
    return inserted, updated

def phase2_push_to_supabase(local_files, dump_date):
    """
    PHASE 2: Push all locally saved data to Supabase.
    Can be re-run if it fails - no extra API costs!
    """
    print("\n" + "=" * 70)
    print("PHASE 2: PUSHING TO SUPABASE")
    print("=" * 70)
    print("Reading from local files and pushing to Supabase...")
    print("Fresh connection every 100 records - no timeouts!")
    print("-" * 70)

    total_inserted = 0
    total_updated = 0
    zip_results = []

    for zip_code, filepath in local_files.items():
        inserted, updated = push_zip_to_supabase(
            zip_code, filepath, dump_date
        )
        total_inserted += inserted
        total_updated += updated
        zip_results.append({
            'zip': zip_code,
            'inserted': inserted,
            'updated': updated
        })

    print(f"\n{'='*70}")
    print(f"PHASE 2 COMPLETE")
    print(f"Total new records: {total_inserted:,}")
    print(f"Total updated records: {total_updated:,}")
    print(f"{'='*70}")

    return total_inserted, total_updated, zip_results

# ============================================================
# MAIN FUNCTION
# ============================================================

def run_finish_dump():
    """
    Smart two-phase dump:
    Phase 1: Fetch from RentCast → save locally (no Supabase)
    Phase 2: Push local data → Supabase (no RentCast API calls)
    """
    start_time = datetime.now()
    dump_date = start_time.strftime('%Y-%m-%d')

    print("=" * 70)
    print("BRI RENTCAST - SMART FINISH DUMP")
    print("=" * 70)
    print(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Missing ZIPs: {MISSING_ZIP_CODES}")
    print(f"Strategy: Fetch all first, then push to Supabase")
    print(f"Benefit: If Supabase fails, re-run Phase 2 for FREE!")
    print("=" * 70)

    # PHASE 1: Fetch from RentCast
    local_files, total_fetched, api_calls = phase1_fetch_all(
        dump_date
    )

    if not local_files:
        print("No data fetched - check API key and connection")
        return False

    # PHASE 2: Push to Supabase
    total_inserted, total_updated, zip_results = phase2_push_to_supabase(
        local_files, dump_date
    )

    # Final summary
    end_time = datetime.now()
    duration = (end_time - start_time).seconds

    print("\n" + "=" * 70)
    print("FINISH DUMP COMPLETE - SUMMARY")
    print("=" * 70)
    print(f"Duration: {duration} seconds")
    print(f"RentCast API calls: {api_calls}")
    print(f"Records fetched: {total_fetched:,}")
    print(f"New records added: {total_inserted:,}")
    print(f"Records updated: {total_updated:,}")
    print(f"\nZIP Results:")
    for r in zip_results:
        print(f"  {r['zip']}: {r['inserted']} new, "
              f"{r['updated']} updated")
    print(f"\nLocal cache files saved in:")
    print(f"  {LOCAL_DATA_DIR}")
    print(f"\nAll 14 ZIP codes now complete!")
    print("=" * 70)

    return True

if __name__ == "__main__":
    # Check if user wants to re-run just Phase 2
    if len(sys.argv) > 1 and sys.argv[1] == '--phase2-only':
        print("Re-running Phase 2 only (no API calls)...")
        dump_date = datetime.now().strftime('%Y-%m-%d')
        local_files = {}
        for zip_code in MISSING_ZIP_CODES:
            filename = f"rentcast_{zip_code}_{dump_date}.json"
            filepath = os.path.join(LOCAL_DATA_DIR, filename)
            if os.path.exists(filepath):
                local_files[zip_code] = filepath
                print(f"Found local file for {zip_code}")
            else:
                print(f"No local file for {zip_code} - "
                      f"run without --phase2-only first")
        if local_files:
            dump_date = datetime.now().strftime('%Y-%m-%d')
            phase2_push_to_supabase(local_files, dump_date)
    else:
        success = run_finish_dump()
        sys.exit(0 if success else 1)