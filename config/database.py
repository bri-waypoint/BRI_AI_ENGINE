# config/database.py
# Supabase database connection for BRI AI Engine
# Queries both BRI Vault AND stored RentCast data

import os
import psycopg2
from dotenv import load_dotenv
from decimal import Decimal

load_dotenv()

def get_connection():
    """Get PostgreSQL connection to Supabase."""
    return psycopg2.connect(
        host=os.getenv('SUPABASE_HOST'),
        database=os.getenv('SUPABASE_DB'),
        user=os.getenv('SUPABASE_USER'),
        password=os.getenv('SUPABASE_PASSWORD'),
        port=int(os.getenv('SUPABASE_PORT', 5432)),
        sslmode='require',
        connect_timeout=10
    )

def clean_value(val):
    """Convert PostgreSQL Decimal types to Python native float."""
    if isinstance(val, Decimal):
        return float(val)
    return val

def get_nearby_vault_properties(lat, lon, radius_miles=3.0,
                                limit=100, property_types=None):
    """
    Get properties from BRI Vault within radius.
    These are properties scraped from Zillow via Bright Data.
    """
    conn = get_connection()
    cursor = conn.cursor()

    if property_types is None:
        property_types = [
            'SINGLE_FAMILY', 'TOWNHOUSE', 'CONDO',
            'Single Family', 'Townhouse', 'Condo'
        ]

    type_placeholders = ','.join(['%s'] * len(property_types))

    query = f"""
        SELECT * FROM (
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
                'BRI Vault' as data_source,
                CAST((
                    3959 * acos(
                        CASE
                            WHEN cos(radians(%s)) *
                                 cos(radians(CAST(latitude AS FLOAT))) *
                                 cos(radians(CAST(longitude AS FLOAT)) -
                                     radians(%s)) +
                                 sin(radians(%s)) *
                                 sin(radians(CAST(latitude AS FLOAT))) > 1
                            THEN 1.0
                            WHEN cos(radians(%s)) *
                                 cos(radians(CAST(latitude AS FLOAT))) *
                                 cos(radians(CAST(longitude AS FLOAT)) -
                                     radians(%s)) +
                                 sin(radians(%s)) *
                                 sin(radians(CAST(latitude AS FLOAT))) < -1
                            THEN -1.0
                            ELSE cos(radians(%s)) *
                                 cos(radians(CAST(latitude AS FLOAT))) *
                                 cos(radians(CAST(longitude AS FLOAT)) -
                                     radians(%s)) +
                                 sin(radians(%s)) *
                                 sin(radians(CAST(latitude AS FLOAT)))
                        END
                    )
                ) AS FLOAT) AS distance_miles
            FROM properties
            WHERE
                latitude IS NOT NULL
                AND longitude IS NOT NULL
                AND current_price IS NOT NULL
                AND current_price > 0
                AND (home_type IN ({type_placeholders})
                     OR home_type IS NULL)
        ) AS subquery
        WHERE distance_miles <= %s
        ORDER BY distance_miles ASC
        LIMIT %s
    """

    params = (
        lat, lon, lat,
        lat, lon, lat,
        lat, lon, lat,
        *property_types,
        radius_miles,
        limit
    )

    cursor.execute(query, params)
    columns = [desc[0] for desc in cursor.description]
    results = []

    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        results.append(prop)

    conn.close()
    return results

def get_nearby_rentcast_properties(lat, lon, radius_miles=3.0,
                                   limit=100, property_types=None):
    """
    Get RentCast listings from Supabase stored data.
    NO live API calls - uses our bi-weekly dump data!
    Returns both Active and Inactive (leased) listings.
    Ordered by: leased first, then by distance.
    """
    conn = get_connection()
    cursor = conn.cursor()

    if property_types is None:
        property_types = ['Single Family', 'Townhouse', 'Condo']

    type_placeholders = ','.join(['%s'] * len(property_types))

    query = f"""
        SELECT * FROM (
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
                'RentCast' as data_source,
                CAST((
                    3959 * acos(
                        CASE
                            WHEN cos(radians(%s)) *
                                 cos(radians(CAST(latitude AS FLOAT))) *
                                 cos(radians(CAST(longitude AS FLOAT)) -
                                     radians(%s)) +
                                 sin(radians(%s)) *
                                 sin(radians(CAST(latitude AS FLOAT))) > 1
                            THEN 1.0
                            WHEN cos(radians(%s)) *
                                 cos(radians(CAST(latitude AS FLOAT))) *
                                 cos(radians(CAST(longitude AS FLOAT)) -
                                     radians(%s)) +
                                 sin(radians(%s)) *
                                 sin(radians(CAST(latitude AS FLOAT))) < -1
                            THEN -1.0
                            ELSE cos(radians(%s)) *
                                 cos(radians(CAST(latitude AS FLOAT))) *
                                 cos(radians(CAST(longitude AS FLOAT)) -
                                     radians(%s)) +
                                 sin(radians(%s)) *
                                 sin(radians(CAST(latitude AS FLOAT)))
                        END
                    )
                ) AS FLOAT) AS distance_miles
            FROM rentcast_listings
            WHERE
                latitude IS NOT NULL
                AND longitude IS NOT NULL
                AND price IS NOT NULL
                AND price > 0
                AND property_type IN ({type_placeholders})
        ) AS subquery
        WHERE distance_miles <= %s
        ORDER BY
            CASE WHEN listing_status = 'Inactive' THEN 0
                 ELSE 1 END,
            distance_miles ASC
        LIMIT %s
    """

    params = (
        lat, lon, lat,
        lat, lon, lat,
        lat, lon, lat,
        *property_types,
        radius_miles,
        limit
    )

    cursor.execute(query, params)
    columns = [desc[0] for desc in cursor.description]
    results = []

    for row in cursor.fetchall():
        prop = {col: clean_value(val)
                for col, val in zip(columns, row)}
        results.append(prop)

    conn.close()
    return results

def get_subject_properties():
    """Get all subject properties that have coordinates."""
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

    # Vault stats
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN listing_status = 'LEASED'
                  THEN 1 END) as leased,
            COUNT(CASE WHEN listing_status = 'ACTIVE'
                  THEN 1 END) as active
        FROM properties
    """)
    vault = cursor.fetchone()

    # RentCast stats
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

    conn.close()

    return {
        'vault_total': vault[0],
        'vault_leased': vault[1],
        'vault_active': vault[2],
        'rentcast_total': rc[0],
        'rentcast_leased': rc[1],
        'rentcast_active': rc[2],
        'rentcast_last_dump': rc[3]
    }