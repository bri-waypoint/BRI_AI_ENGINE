# app/bri_ai_engine.py
# BRI AI Engine - Core analysis using Claude API
# Fixed for Streamlit Cloud - reads secrets from st.secrets
# FIXED: vault leased filter now catches all LEASED status
#        variants (LEASED, LEASED_RECENT, LEASED_HISTORICAL,
#        LEASED_DATED) so no leased comps are missed

import os
import sys
import anthropic
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Fix paths for Streamlit Cloud
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.insert(0, root_dir)
sys.path.insert(0, current_dir)

from config.database import (
    get_nearby_vault_properties,
    get_nearby_rentcast_properties
)
from config.prompt import build_analysis_prompt

load_dotenv()

def get_claude_api_key():
    """Get Claude API key from Streamlit secrets or environment."""
    try:
        import streamlit as st
        return st.secrets["CLAUDE_API_KEY"]
    except Exception:
        return os.getenv("CLAUDE_API_KEY")

def sort_by_recency_then_distance(properties):
    """Sort properties by most recent first, then by closest distance."""
    def sort_key(prop):
        date_str = (prop.get("last_seen_date", "2000-01-01") or "2000-01-01")
        distance = float(prop.get("distance_miles") or 99)
        try:
            date_val = datetime.strptime(date_str[:10], "%Y-%m-%d")
            days_ago = (datetime.now() - date_val).days
        except Exception:
            days_ago = 9999
        return (days_ago, distance)
    return sorted(properties, key=sort_key)

def filter_to_recent(properties, months=15):
    """Filter leased properties to only include those within the last N months."""
    cutoff = (datetime.now() - timedelta(days=months * 30.5))
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    recent = []
    removed = 0
    for p in properties:
        status = (p.get("listing_status", "") or "").upper()
        date_str = (p.get("last_seen_date", "") or "")
        if "ACTIVE" in status:
            recent.append(p)
            continue
        if date_str[:10] >= cutoff_str:
            recent.append(p)
        else:
            removed += 1
    return recent, removed

def is_leased_status(listing_status):
    """
    Check if a listing status indicates a leased property.
    Catches all variants BrightData/Zillow may return:
    - LEASED         (set by our mark_inactive_properties fix)
    - LEASED_RECENT  (sent directly by BrightData/Zillow)
    - LEASED_HISTORICAL (sent directly by BrightData/Zillow)
    - LEASED_DATED   (sent directly by BrightData/Zillow)
    """
    status = (listing_status or "").upper()
    return status.startswith("LEASED")

def is_active_status(listing_status):
    """Check if a listing status indicates an active property."""
    status = (listing_status or "").upper()
    return "ACTIVE" in status

def analyze_property(subject, radius_miles=3.0, property_types=None, use_rentcast=True):
    """
    Main analysis function combining BRI Vault + RentCast data.
    Filters to last 15 months, sorts by recency then distance.
    """
    if property_types is None:
        vault_types = [
            "SINGLE_FAMILY", "TOWNHOUSE", "CONDO",
            "Single Family", "Townhouse", "Condo"
        ]
    else:
        vault_types = property_types

    rc_map = {
        "SINGLE_FAMILY": "Single Family",
        "TOWNHOUSE": "Townhouse",
        "CONDO": "Condo",
        "APARTMENT": "Apartment",
        "MULTI_FAMILY": "Multi-Family",
        "Single Family": "Single Family",
        "Townhouse": "Townhouse",
        "Condo": "Condo",
        "Apartment": "Apartment"
    }
    rc_types = list(set([rc_map[t] for t in vault_types if t in rc_map]))
    if not rc_types:
        rc_types = ["Single Family", "Townhouse", "Condo"]

    print(f"BRI AI ANALYSIS")
    print(f"Property: {subject.get('address')}, {subject.get('city')}")
    print(f"Radius: {radius_miles} miles")

    # STEP 1: Get BRI Vault properties
    print("[1] BRI Vault search...")
    vault_props = get_nearby_vault_properties(
        lat=float(subject["latitude"]),
        lon=float(subject["longitude"]),
        radius_miles=radius_miles,
        limit=150,
        property_types=vault_types
    )

    # FIXED: use is_leased_status() to catch all LEASED variants
    vault_leased_raw = [
        p for p in vault_props
        if is_leased_status(p.get("listing_status"))
    ]
    vault_active = [
        p for p in vault_props
        if is_active_status(p.get("listing_status"))
    ]
    vault_leased, vault_removed = filter_to_recent(vault_leased_raw, months=15)
    vault_leased = sort_by_recency_then_distance(vault_leased)
    print(f"   Vault leased: {len(vault_leased)} recent ({vault_removed} older removed)")
    print(f"   Vault active: {len(vault_active)}")

    # STEP 2: Get stored RentCast properties
    rc_leased = []
    rc_active = []

    if use_rentcast:
        print("[2] RentCast stored data search...")
        rc_props = get_nearby_rentcast_properties(
            lat=float(subject["latitude"]),
            lon=float(subject["longitude"]),
            radius_miles=radius_miles,
            limit=150,
            property_types=rc_types
        )
        rc_leased_raw = [
            p for p in rc_props
            if p.get("listing_status") == "Inactive"
        ]
        rc_active = [
            p for p in rc_props
            if p.get("listing_status") == "Active"
        ]
        rc_leased, rc_removed = filter_to_recent(rc_leased_raw, months=15)
        rc_leased = sort_by_recency_then_distance(rc_leased)
        print(f"   RentCast leased: {len(rc_leased)} recent ({rc_removed} older removed)")
        print(f"   RentCast active: {len(rc_active)}")

    # Auto-expand radius if not enough recent leased comps
    total_leased = len(vault_leased) + len(rc_leased)
    if total_leased < 5 and radius_miles < 5.0:
        print(f"   Only {total_leased} recent leased comps. Expanding to 5 miles...")
        vault_props = get_nearby_vault_properties(
            lat=float(subject["latitude"]),
            lon=float(subject["longitude"]),
            radius_miles=5.0,
            limit=150,
            property_types=vault_types
        )
        # FIXED: use is_leased_status() here too
        vault_leased_raw = [
            p for p in vault_props
            if is_leased_status(p.get("listing_status"))
        ]
        vault_active = [
            p for p in vault_props
            if is_active_status(p.get("listing_status"))
        ]
        vault_leased, _ = filter_to_recent(vault_leased_raw, months=15)
        vault_leased = sort_by_recency_then_distance(vault_leased)

        if use_rentcast:
            rc_props = get_nearby_rentcast_properties(
                lat=float(subject["latitude"]),
                lon=float(subject["longitude"]),
                radius_miles=5.0,
                limit=150,
                property_types=rc_types
            )
            rc_leased_raw = [
                p for p in rc_props
                if p.get("listing_status") == "Inactive"
            ]
            rc_active = [
                p for p in rc_props
                if p.get("listing_status") == "Active"
            ]
            rc_leased, _ = filter_to_recent(rc_leased_raw, months=15)
            rc_leased = sort_by_recency_then_distance(rc_leased)

        total_leased = len(vault_leased) + len(rc_leased)
        print(f"   Expanded total recent leased: {total_leased}")

    # STEP 3: Build prompt
    print("[3] Building analysis prompt...")
    current_date = datetime.now().strftime("%B %d, %Y")
    rentcast_data = {
        "leased": rc_leased,
        "active": rc_active,
        "estimate": None,
        "market_stats": None
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
    print("[4] Sending to Claude AI...")
    api_key = get_claude_api_key()
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    analysis = message.content[0].text
    total_active = len(vault_active) + len(rc_active)
    total_leased = len(vault_leased) + len(rc_leased)
    print(f"   Complete! Used {total_leased} leased + {total_active} active comps")

    return {
        "analysis": analysis,
        "vault_leased": vault_leased,
        "vault_active": vault_active,
        "rentcast_leased": rc_leased,
        "rentcast_active": rc_active,
        "total_leased": total_leased,
        "total_active": total_active,
        "radius_used": radius_miles,
        "subject": subject,
        "current_date": current_date
    }