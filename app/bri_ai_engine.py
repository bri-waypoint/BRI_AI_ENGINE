# app/bri_ai_engine.py
# BRI AI Engine - Core analysis using Claude API
# Combines BRI Vault + stored RentCast data for maximum accuracy

import os
import sys
import anthropic
from dotenv import load_dotenv
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.database import (get_nearby_vault_properties,
                              get_nearby_rentcast_properties)
from config.prompt import build_analysis_prompt

load_dotenv()

def analyze_property(subject, radius_miles=3.0,
                     property_types=None, use_rentcast=True):
    """
    Main analysis function combining BRI Vault + RentCast data.
    Sends combined dataset to Claude for intelligent analysis.

    Args:
        subject: Subject property dictionary
        radius_miles: Search radius in miles
        property_types: List of property types to include
        use_rentcast: Whether to include stored RentCast data

    Returns:
        Dictionary with complete analysis results
    """

    # Vault property types (our internal format)
    if property_types is None:
        vault_types = [
            'SINGLE_FAMILY', 'TOWNHOUSE', 'CONDO',
            'Single Family', 'Townhouse', 'Condo'
        ]
    else:
        vault_types = property_types

    # RentCast property types (their format - case sensitive!)
    rc_types = ['Single Family', 'Townhouse', 'Condo']
    if property_types:
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
            rc_map[t] for t in property_types
            if t in rc_map
        ]))
        if not rc_types:
            rc_types = ['Single Family', 'Townhouse', 'Condo']

    print(f"\n{'='*60}")
    print(f"BRI AI ANALYSIS")
    print(f"{'='*60}")
    print(f"Property: {subject.get('address')}, "
          f"{subject.get('city')}")
    print(f"Radius: {radius_miles} miles")

    # STEP 1: Get BRI Vault properties
    print(f"\n[1] BRI Vault search...")
    vault_props = get_nearby_vault_properties(
        lat=float(subject['latitude']),
        lon=float(subject['longitude']),
        radius_miles=radius_miles,
        limit=100,
        property_types=vault_types
    )

    vault_leased = [p for p in vault_props
                    if p.get('listing_status') == 'LEASED']
    vault_active = [p for p in vault_props
                    if p.get('listing_status') == 'ACTIVE']
    print(f"   Found: {len(vault_leased)} leased, "
          f"{len(vault_active)} active")

    # STEP 2: Get stored RentCast properties
    rc_leased = []
    rc_active = []

    if use_rentcast:
        print(f"\n[2] RentCast stored data search...")
        rc_props = get_nearby_rentcast_properties(
            lat=float(subject['latitude']),
            lon=float(subject['longitude']),
            radius_miles=radius_miles,
            limit=100,
            property_types=rc_types
        )

        rc_leased = [p for p in rc_props
                     if p.get('listing_status') == 'Inactive']
        rc_active = [p for p in rc_props
                     if p.get('listing_status') == 'Active']
        print(f"   Found: {len(rc_leased)} leased, "
              f"{len(rc_active)} active")
    else:
        print(f"\n[2] RentCast disabled")

    # Auto-expand radius if not enough leased comps
    total_leased = len(vault_leased) + len(rc_leased)
    if total_leased < 5 and radius_miles < 5.0:
        print(f"\n   Only {total_leased} leased found. "
              f"Expanding to 5 miles...")

        vault_props = get_nearby_vault_properties(
            lat=float(subject['latitude']),
            lon=float(subject['longitude']),
            radius_miles=5.0,
            limit=100,
            property_types=vault_types
        )
        vault_leased = [p for p in vault_props
                        if p.get('listing_status') == 'LEASED']
        vault_active = [p for p in vault_props
                        if p.get('listing_status') == 'ACTIVE']

        if use_rentcast:
            rc_props = get_nearby_rentcast_properties(
                lat=float(subject['latitude']),
                lon=float(subject['longitude']),
                radius_miles=5.0,
                limit=100,
                property_types=rc_types
            )
            rc_leased = [p for p in rc_props
                         if p.get('listing_status') == 'Inactive']
            rc_active = [p for p in rc_props
                         if p.get('listing_status') == 'Active']

        total_leased = len(vault_leased) + len(rc_leased)
        print(f"   Expanded total leased: {total_leased}")

    # STEP 3: Build prompt with ALL data
    print(f"\n[3] Building analysis prompt...")
    current_date = datetime.now().strftime("%B %d, %Y")

    rentcast_data = {
        'leased': rc_leased,
        'active': rc_active,
        'estimate': None,
        'market_stats': None
    }

    prompt = build_analysis_prompt(
        subject=subject,
        nearby_properties=vault_leased + vault_active,
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

    print(f"   Complete! Used {total_leased} leased + "
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