# app/bri_ai_engine.py
# BRI AI Engine - Core analysis using Claude API
# Fixed for Streamlit Cloud - reads secrets from st.secrets
# UPDATED: Split into two functions:
#   get_comparable_properties() - fetches and ranks comps only
#   generate_report() - takes selected comps and calls Claude
# FIXED: vault leased filter catches all LEASED status variants

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

def get_comparable_properties(subject, radius_miles=3.0,
                               property_types=None,
                               use_rentcast=True):
    """
    STEP 1 of new two-step workflow.
    Fetches, ranks, and returns top 15 leased and top 15 active
    comps without calling Claude. Shannyn reviews and selects
    which ones to use before analysis begins.
    Returns a dict with leased and active lists.
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

    print(f"BRI COMP SEARCH")
    print(f"Property: {subject.get('address')}, {subject.get('city')}")
    print(f"Radius: {radius_miles} miles")

    # Get BRI Vault properties
    print("[1] BRI Vault search...")
    vault_props = get_nearby_vault_properties(
        lat=float(subject["latitude"]),
        lon=float(subject["longitude"]),
        radius_miles=radius_miles,
        limit=150,
        property_types=vault_types
    )

    vault_leased_raw = [
        p for p in vault_props
        if is_leased_status(p.get("listing_status"))
    ]
    vault_active = [
        p for p in vault_props
        if is_active_status(p.get("listing_status"))
    ]
    vault_leased, vault_removed = filter_to_recent(
        vault_leased_raw, months=15
    )
    vault_leased = sort_by_recency_then_distance(vault_leased)
    print(f"   Vault leased: {len(vault_leased)} recent "
          f"({vault_removed} older removed)")
    print(f"   Vault active: {len(vault_active)}")

    # Get RentCast properties
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
        rc_leased, rc_removed = filter_to_recent(
            rc_leased_raw, months=15
        )
        rc_leased = sort_by_recency_then_distance(rc_leased)
        print(f"   RentCast leased: {len(rc_leased)} recent "
              f"({rc_removed} older removed)")
        print(f"   RentCast active: {len(rc_active)}")

    # Auto-expand radius if not enough recent leased comps
    total_leased = len(vault_leased) + len(rc_leased)
    expanded = False
    if total_leased < 5 and radius_miles < 5.0:
        print(f"   Only {total_leased} recent leased comps. "
              f"Expanding to 5 miles...")
        vault_props = get_nearby_vault_properties(
            lat=float(subject["latitude"]),
            lon=float(subject["longitude"]),
            radius_miles=5.0,
            limit=150,
            property_types=vault_types
        )
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

        radius_miles = 5.0
        expanded = True
        total_leased = len(vault_leased) + len(rc_leased)
        print(f"   Expanded total recent leased: {total_leased}")

    # Combine and return top 15 of each category
    all_leased = vault_leased + rc_leased
    all_leased = sort_by_recency_then_distance(all_leased)

    all_active = vault_active + rc_active
    all_active = sort_by_recency_then_distance(all_active)

    print(f"   Returning top 15 leased and top 15 active for review")

    return {
        "leased": all_leased[:15],
        "active": all_active[:15],
        "vault_leased_count": len(vault_leased),
        "rentcast_leased_count": len(rc_leased),
        "total_leased": total_leased,
        "total_active": len(all_active),
        "radius_used": radius_miles,
        "radius_expanded": expanded
    }

def generate_report(subject, selected_leased, selected_active):
    """
    STEP 2 of new two-step workflow.
    Takes Shannyn's selected comps and generates the
    Claude AI analysis report based only on those comps.
    Returns the full result dict including analysis text.
    """
    print(f"BRI AI ANALYSIS")
    print(f"Property: {subject.get('address')}, {subject.get('city')}")
    print(f"Selected leased comps: {len(selected_leased)}")
    print(f"Selected active comps: {len(selected_active)}")

    # Build prompt with only selected comps
    print("[1] Building analysis prompt...")
    current_date = datetime.now().strftime("%B %d, %Y")

    rentcast_leased = [
        p for p in selected_leased
        if p.get("data_source") == "RentCast"
    ]
    vault_leased = [
        p for p in selected_leased
        if p.get("data_source") == "BRI Vault"
    ]
    rentcast_active = [
        p for p in selected_active
        if p.get("data_source") == "RentCast"
    ]
    vault_active = [
        p for p in selected_active
        if p.get("data_source") == "BRI Vault"
    ]

    rentcast_data = {
        "leased": rentcast_leased,
        "active": rentcast_active,
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

    # Call Claude AI
    print("[2] Sending to Claude AI...")
    api_key = get_claude_api_key()
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    analysis = message.content[0].text

    total_leased = len(selected_leased)
    total_active = len(selected_active)
    print(f"   Complete! Used {total_leased} leased "
          f"+ {total_active} active comps")

    return {
        "analysis": analysis,
        "vault_leased": vault_leased,
        "vault_active": vault_active,
        "rentcast_leased": rentcast_leased,
        "rentcast_active": rentcast_active,
        "total_leased": total_leased,
        "total_active": total_active,
        "subject": subject,
        "current_date": current_date,
        "selected_leased": selected_leased,
        "selected_active": selected_active
    }

def analyze_property(subject, radius_miles=3.0,
                     property_types=None, use_rentcast=True):
    """
    Legacy single-step function kept for one-off searches.
    Combines get_comparable_properties and generate_report
    into one call for the one-off search workflow.
    """
    if property_types is None:
        vault_types = [
            "SINGLE_FAMILY", "TOWNHOUSE", "CONDO",
            "Single Family", "Townhouse", "Condo"
        ]
    else:
        vault_types = property_types

    # Get comps
    comp_result = get_comparable_properties(
        subject=subject,
        radius_miles=radius_miles,
        property_types=vault_types,
        use_rentcast=use_rentcast
    )

    # Use all returned comps without selection step
    selected_leased = comp_result["leased"]
    selected_active = comp_result["active"]

    # Generate report
    result = generate_report(subject, selected_leased, selected_active)
    result["radius_used"] = comp_result["radius_used"]
    return result
