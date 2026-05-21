# app/bri_ai_engine.py
# BRI AI Engine - Core analysis using Claude API
# UPDATED: Uses four-round appraisal comp search from database.py
# Two-step workflow:
#   get_comparable_properties() - runs appraisal search, no Claude
#   generate_report() - takes selected comps, calls Claude

import os
import sys
import anthropic
from dotenv import load_dotenv
from datetime import datetime

# Fix paths for Streamlit Cloud
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.insert(0, root_dir)
sys.path.insert(0, current_dir)

from config.database import (
    run_comp_search,
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

def get_comparable_properties(subject, use_rentcast=True,
                               radius_miles=None,
                               property_types=None):
    """
    STEP 1 of two-step workflow.
    Runs four-round appraisal comp search.
    Returns top 30 leased and top 30 active comps
    for Shannyn to review and select from.
    radius_miles and property_types are ignored here —
    the appraisal search manages its own radius expansion.
    """
    print(f"BRI APPRAISAL COMP SEARCH")
    print(f"Property: {subject.get('address')}, "
          f"{subject.get('city')}")

    result = run_comp_search(
        subject=subject,
        use_rentcast=use_rentcast
    )

    return result

def generate_report(subject, selected_leased, selected_active):
    """
    STEP 2 of two-step workflow.
    Takes Shannyn's selected comps and generates
    the Claude AI analysis report.
    """
    print(f"BRI AI ANALYSIS")
    print(f"Property: {subject.get('address')}, "
          f"{subject.get('city')}")
    print(f"Selected leased: {len(selected_leased)}")
    print(f"Selected active: {len(selected_active)}")

    current_date = datetime.now().strftime("%B %d, %Y")

    # Split by source for prompt builder
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
    print("[1] Building analysis prompt...")
    prompt = build_analysis_prompt(
        subject=subject,
        nearby_properties=all_vault,
        rentcast_data=rentcast_data,
        current_date=current_date
    )
    print(f"   Prompt: {len(prompt):,} characters")

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
    Legacy single-step function for one-off searches.
    Runs appraisal search then generates report in one call.
    """
    comp_result = get_comparable_properties(
        subject=subject,
        use_rentcast=use_rentcast
    )

    selected_leased = comp_result["leased"]
    selected_active = comp_result["active"]

    result = generate_report(subject, selected_leased, selected_active)
    result["radius_used"] = comp_result["radius_used"]
    result["confidence"] = comp_result["confidence"]
    result["round_stopped"] = comp_result["round_stopped"]
    return result
