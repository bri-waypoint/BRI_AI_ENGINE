# scripts/keep_alive.py
# Keeps Supabase database active by running simple queries
# Prevents the free tier from pausing due to inactivity
# Schedule this to run every Sunday and Wednesday at 8AM

import os
import sys
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(__file__)), '.env'
))

SUPABASE_CONFIG = {
    'host': os.getenv('SUPABASE_HOST'),
    'database': os.getenv('SUPABASE_DB'),
    'user': os.getenv('SUPABASE_USER'),
    'password': os.getenv('SUPABASE_PASSWORD'),
    'port': int(os.getenv('SUPABASE_PORT', 5432)),
    'sslmode': 'require',
    'connect_timeout': 30
}

def run_keep_alive():
    """
    Run simple queries to keep Supabase active.
    Supabase pauses free tier projects after 7 days of inactivity.
    Running this bi-weekly prevents that from happening.
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    print("=" * 60)
    print("BRI SUPABASE KEEP-ALIVE")
    print("=" * 60)
    print(f"Timestamp: {timestamp}")

    try:
        print("\n[1] Connecting to Supabase...")
        conn = psycopg2.connect(**SUPABASE_CONFIG)
        cursor = conn.cursor()
        print("    Connected!")

        # Query 1: Count properties
        cursor.execute("SELECT COUNT(*) FROM properties")
        prop_count = cursor.fetchone()[0]
        print(f"\n[2] Properties table: {prop_count:,} records")

        # Query 2: Count RentCast listings
        cursor.execute("SELECT COUNT(*) FROM rentcast_listings")
        rc_count = cursor.fetchone()[0]
        print(f"[3] RentCast table: {rc_count:,} records")

        # Query 3: Count subject properties
        cursor.execute("SELECT COUNT(*) FROM subject_properties")
        sub_count = cursor.fetchone()[0]
        print(f"[4] Subject properties: {sub_count:,} records")

        # Query 4: Check last RentCast dump
        cursor.execute(
            "SELECT MAX(dump_date) FROM rentcast_listings"
        )
        last_dump = cursor.fetchone()[0]
        print(f"[5] Last RentCast dump: {last_dump}")

        conn.close()

        print("\n" + "=" * 60)
        print("KEEP-ALIVE SUCCESSFUL")
        print("=" * 60)
        print(f"Total records: {prop_count + rc_count + sub_count:,}")
        print(f"Database is active and healthy!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        print("Database may be paused - check Supabase dashboard")
        return False

if __name__ == "__main__":
    success = run_keep_alive()
    sys.exit(0 if success else 1)