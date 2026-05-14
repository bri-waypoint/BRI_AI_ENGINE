# app/bri_ai_engine.py
# BRI AI Engine - Core analysis using Claude API
# Combines BRI Vault + stored RentCast data
# Filters to last 15 months, sorts by recency then distance

import os
import sys
import anthropic
from dotenv import load_dotenv
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.database import (get_nearby_vault_properties,
                              get_nearby_rentcast_properties)
from config.prompt import build_analysis_prompt

load_dotenv()

def sort_by_recency_then_distance(properties):
    """
    Sort properties by most recent first, then by closest distance.
    This ensures Claude sees the best comps first.
    """
    def sort_key(prop):
        date_str = (prop.get('last_seen_date', '2000-01-01')
                    or '2000-01-01')
        distance = float(prop.get('distance_miles') or 99)
        try:
            date_val = datetime.strptime(date_str[:10], '%Y-%m-%d')
            days_ago = (datetime.now() - date_val).days
        except Exception:
            days_ago = 9999
        return (days_ago, distance)

    return sorted(properties, key=sort_key)

def filter_to_recent(properties, months=15):
    """
    Filter leased properties to only include those
    within the last N months. Always keeps active listings.
    """
    cutoff = (datetime.now() - timedelta(days=months * 30.5))
    cutoff_str = cutoff.strftime('%Y-%m-%d')

    recent = []
    removed = 0

    for p in properties:
        status = (p.get('listing_status', '') or '').upper()
        date_str = (p.get('last_seen_date', '') or '')

        # Always keep active listings
        if 'ACTIVE' in status:
            recent.append(p)
            continue

        # For leased properties, check the date
        if date_str[:10] >= cutoff_str:
            recent.append(p)
        else:
            removed += 1

    return recent, removed

def analyze_property(subject, radius_miles=3.0,
                     property_types=None, use_rentcast=True):
    """
    Main analysis function combining BRI Vault + RentCast data.
    Filters to last 15 months, sorts by recency then distance.
    Sends combined dataset to Claude for intelligent analysis.
    """

    # Vault property types
    if property_types is None:
        vault_types = [
            'SINGLE_FAMILY', 'TOWNHOUSE', 'CONDO',
            'Single Family', 'Townhouse', 'Condo'
        ]
    else:
        vault_types = property_types

    # RentCast property types (case sensitive!)
    rc_map = {
        'SINGLE_FAMILY': 'Single Family',
        'TOWNHOUSE': 'Townhouse',
        'CONDO': 'Condo',
        'APARTMENT': 'Apartment',
        'MULTI_FAMILY': 'Multi-Family',
        'Single Family': 'Single Family',
        'Townhouse': 'Townhouse',
        'Condo': 'Condo',
        'Apartment': 'Apartment'
    }
    rc_types = list(set([
        rc_map[t] for t in vault_types if t in rc_map
    ]))
    if not rc_types:
        rc_types = ['Single Family', 'Townhouse', 'Condo']

    print(f"\n{'='*60}")
    print(f"BRI AI ANALYSIS")
    print(f"{'='*60}")
    print(f"Property: {subject.get('address')}, "
          f"{subject.get('city')}")
    print(f"Radius: {radius_miles} miles")
    print(f"15-month cutoff: "
          f"{(datetime.now() - timedelta(days=456)).strftime('%Y-%m-%d')}")

    # STEP 1: Get BRI Vault properties
    print(f"\n[1] BRI Vault search...")
    vault_props = get_nearby_vault_properties(
        lat=float(subject['latitude']),
        lon=float(subject['longitude']),
        radius_miles=radius_miles,
        limit=150,
        property_types=vault_types
    )

    vault_leased_raw = [p for p in vault_props
                        if p.get('listing_status') == 'LEASED']
    vault_active = [p for p in vault_props
                    if 'ACTIVE' in str(
                        p.get('listing_status', '')).upper()]

    vault_leased, vault_removed = filter_to_recent(
        vault_leased_raw, months=15
    )
    vault_leased = sort_by_recency_then_distance(vault_leased)

    print(f"   Vault leased: {len(vault_leased)} recent "
          f"({vault_removed} older than 15mo removed)")
    print(f"   Vault active: {len(vault_active)}")

    # STEP 2: Get stored RentCast properties
    rc_leased = []
    rc_active = []

    if use_rentcast:
        print(f"\n[2] RentCast stored data search...")
        rc_props = get_nearby_rentcast_properties(
            lat=float(subject['latitude']),
            lon=float(subject['longitude']),
            radius_miles=radius_miles,
            limit=150,
            property_types=rc_types
        )

        rc_leased_raw = [p for p in rc_props
                         if p.get('listing_status') == 'Inactive']
        rc_active = [p for p in rc_props
                     if p.get('listing_status') == 'Active']

        rc_leased, rc_removed = filter_to_recent(
            rc_leased_raw, months=15
        )
        rc_leased = sort_by_recency_then_distance(rc_leased)

        print(f"   RentCast leased: {len(rc_leased)} recent "
              f"({rc_removed} older than 15mo removed)")
        print(f"   RentCast active: {len(rc_active)}")
    else:
        print(f"\n[2] RentCast disabled")

    # Auto-expand radius if not enough recent leased comps
    total_leased = len(vault_leased) + len(rc_leased)

    if total_leased < 5 and radius_miles < 5.0:
        print(f"\n   Only {total_leased} recent leased comps found.")
        print(f"   Expanding search to 5 miles...")

        vault_props = get_nearby_vault_properties(
            lat=float(subject['latitude']),
            lon=float(subject['longitude']),
            radius_miles=5.0,
            limit=150,
            property_types=vault_types
        )
        vault_leased_raw = [p for p in vault_props
                            if p.get('listing_status') == 'LEASED']
        vault_active = [p for p in vault_props
                        if 'ACTIVE' in str(
                            p.get('listing_status', '')).upper()]
        vault_leased, vault_removed = filter_to_recent(
            vault_leased_raw, months=15
        )
        vault_leased = sort_by_recency_then_distance(vault_leased)

        if use_rentcast:
            rc_props = get_nearby_rentcast_properties(
                lat=float(subject['latitude']),
                lon=float(subject['longitude']),
                radius_miles=5.0,
                limit=150,
                property_types=rc_types
            )
            rc_leased_raw = [p for p in rc_props
                             if p.get('listing_status') == 'Inactive']
            rc_active = [p for p in rc_props
                         if p.get('listing_status') == 'Active']
            rc_leased, rc_removed = filter_to_recent(
                rc_leased_raw, months=15
            )
            rc_leased = sort_by_recency_then_distance(rc_leased)

        total_leased = len(vault_leased) + len(rc_leased)
        print(f"   Expanded total recent leased: {total_leased}")

    # STEP 3: Build prompt with ALL data
    print(f"\n[3] Building analysis prompt...")
    current_date = datetime.now().strftime("%B %d, %Y")

    rentcast_data = {
        'leased': rc_leased,
        'active': rc_active,
        'estimate': None,
        'market_stats': None
    }

    all_vault = vault_leased + vault_active

    prompt = build_analysis_prompt(
        subject=subject,
        nearby_properties=all_vault,
        rentcast_data=rentcast_data,
        current_date=current_date
    )
    print(f"   Prompt: {len(prompt):,} characters")

    # STEP 4: Claude AI analysis
    print(f"\n[4] Sending to Claude AI...")
    client = anthropic.Anthropic(
        api_key=os.getenv('CLAUDE_API_KEY')
    )

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}]
    )

    analysis = message.content[0].text
    total_active = len(vault_active) + len(rc_active)
    total_leased = len(vault_leased) + len(rc_leased)

    print(f"   Complete!")
    print(f"   Used {total_leased} recent leased + "
          f"{total_active} active comps")
    print(f"{'='*60}\n")

    return {
        'analysis': analysis,
        'vault_leased': vault_leased,
        'vault_active': vault_active,
        'rentcast_leased': rc_leased,
        'rentcast_active': rc_active,
        'total_leased': total_leased,
        'total_active': total_active,
        'radius_used': radius_miles,
        'subject': subject,
        'current_date': current_date
    }