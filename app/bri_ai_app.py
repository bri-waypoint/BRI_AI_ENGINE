# app/bri_ai_app.py
# BRI AI Engine - Streamlit Interface
# Fixed for Streamlit Cloud deployment - correct import paths

import streamlit as st
import pandas as pd
import os
import sys
import urllib.parse
from datetime import datetime

# ============================================================
# FIX IMPORT PATHS FOR STREAMLIT CLOUD
# ============================================================
# Get the directory containing this file (app/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the root directory (BRI_AI_Engine/)
root_dir = os.path.dirname(current_dir)
# Add both to path so imports work on local AND Streamlit Cloud
sys.path.insert(0, root_dir)
sys.path.insert(0, current_dir)

# ============================================================
# IMPORTS - Using direct imports that work on Streamlit Cloud
# ============================================================
from config.database import (
    get_subject_properties,
    get_database_stats,
    save_one_off_search,
    get_recent_one_off_searches
)

# Import analyze_property from same directory
from bri_ai_engine import analyze_property

# ============================================================
# PAGE CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="BRI AI Engine",
    page_icon="ðŸ ",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def make_zillow_url(address, city, state):
    """Generate a Zillow search URL."""
    try:
        full = f"{address} {city} {state}"
        encoded = urllib.parse.quote(full)
        return f"https://www.zillow.com/homes/{encoded}_rb/"
    except Exception:
        return None

def make_google_maps_url(address, city, state):
    """Generate a Google Maps search URL."""
    try:
        full = f"{address}, {city}, {state}"
        encoded = urllib.parse.quote(full)
        return f"https://www.google.com/maps/search/?api=1&query={encoded}"
    except Exception:
        return None

def add_links_to_dataframe(df):
    """Add clickable Zillow and Google Maps links."""
    links = []
    for _, row in df.iterrows():
        addr = str(row.get("Address", "") or "")
        city = str(row.get("City", "") or "")
        zillow = make_zillow_url(addr, city, "ID")
        maps = make_google_maps_url(addr, city, "ID")
        parts = []
        if zillow:
            parts.append(f'<a href="{zillow}" target="_blank">ðŸ  Zillow</a>')
        if maps:
            parts.append(f'<a href="{maps}" target="_blank">ðŸ“ Map</a>')
        links.append(" | ".join(parts) if parts else "N/A")
    df = df.copy()
    df["Links"] = links
    return df

def show_property_table(props, price_col="Rent/Mo"):
    """Display property table with clickable links."""
    if not props:
        st.info("No properties in this category.")
        return
    df = pd.DataFrame(props)
    col_map = {
        "address": "Address",
        "city": "City",
        "bedrooms": "Beds",
        "bathrooms": "Baths",
        "living_area": "SqFt",
        "current_price": price_col,
        "last_seen_date": "Date",
        "distance_miles": "Miles",
        "home_type": "Type",
        "data_source": "Source",
    }
    avail = {k: v for k, v in col_map.items() if k in df.columns}
    display_df = df[list(avail.keys())].copy()
    display_df.columns = list(avail.values())
    display_df = add_links_to_dataframe(display_df)
    st.write(
        display_df.to_html(escape=False, index=False, classes="dataframe"),
        unsafe_allow_html=True,
    )
    st.caption(f"Showing {len(props)} properties")

def run_analysis_and_display(subject, radius, property_types, use_rentcast, selected_type):
    """Run AI analysis and display results."""
    with st.spinner("Searching BRI Vault + RentCast and analyzing with Claude AI... (30-60 seconds)"):
        try:
            result = analyze_property(
                subject=subject,
                radius_miles=radius,
                property_types=property_types,
                use_rentcast=use_rentcast,
            )
            st.session_state["result"] = result
            st.session_state["done"] = True
            st.session_state["analyzed_address"] = subject.get("address", "")
        except Exception as e:
            st.error(f"Analysis failed: {str(e)}")
            st.exception(e)
            return

    result = st.session_state["result"]
    st.markdown("---")
    st.markdown("## Analysis Results")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Vault Leased", len(result.get("vault_leased", [])))
    with col2:
        st.metric("RentCast Leased", len(result.get("rentcast_leased", [])))
    with col3:
        st.metric("Total Leased", result.get("total_leased", 0))
    with col4:
        st.metric("Active Listings", result.get("total_active", 0))
    with col5:
        st.metric("Radius", f"{result.get('radius_used', 3)} mi")

    total_leased = result.get("total_leased", 0)
    if total_leased >= 10:
        st.success(f"âœ… HIGH CONFIDENCE - {total_leased} recent leased comps")
    elif total_leased >= 5:
        st.warning(f"âš ï¸ MEDIUM CONFIDENCE - {total_leased} recent leased comps")
    else:
        st.error(f"âŒ LOW CONFIDENCE - Only {total_leased} recent leased comps")

    st.markdown("---")
    st.markdown(result["analysis"])

    st.markdown("---")
    st.markdown("### ðŸ”— Comparable Property Data")

    tab1, tab2, tab3, tab4 = st.tabs([
        f"ðŸ”‘ Vault Leased ({len(result.get('vault_leased', []))})",
        f"ðŸ† RentCast Leased ({len(result.get('rentcast_leased', []))})",
        f"ðŸ“Š Vault Active ({len(result.get('vault_active', []))})",
        f"ðŸ“‹ RentCast Active ({len(result.get('rentcast_active', []))})",
    ])
    with tab1:
        show_property_table(result.get("vault_leased", []), "Leased/Mo")
    with tab2:
        show_property_table(result.get("rentcast_leased", []), "Leased/Mo")
    with tab3:
        show_property_table(result.get("vault_active", []), "Asking/Mo")
    with tab4:
        show_property_table(result.get("rentcast_active", []), "Asking/Mo")

    st.markdown("---")
    addr = subject.get("address", "property")
    export_text = f"""BRI RENTAL ANALYSIS REPORT
Generated: {datetime.now().strftime("%B %d, %Y %I:%M %p")}
Property: {subject["address"]}, {subject.get("city", "")}
Search Radius: {result.get("radius_used")} miles

{"="*60}

{result["analysis"]}

{"="*60}
DATA SUMMARY:
Vault Leased: {len(result.get("vault_leased", []))}
RentCast Leased: {len(result.get("rentcast_leased", []))}
Total Leased Comps: {result.get("total_leased", 0)}
Total Active Comps: {result.get("total_active", 0)}
"""
    st.download_button(
        label="ðŸ“„ Download Analysis Report",
        data=export_text,
        file_name=f"BRI_{addr.replace(' ', '_')}.txt",
        mime="text/plain",
        use_container_width=True,
    )

# ============================================================
# LOAD DATA
# ============================================================

@st.cache_data(ttl=300)
def load_stats():
    return get_database_stats()

@st.cache_data(ttl=300)
def load_subjects():
    return get_subject_properties()

stats = load_stats()
subjects = load_subjects()

# ============================================================
# HEADER
# ============================================================
st.markdown("""
# ðŸ  BRI AI Rental Analysis Engine
*Powered by Claude AI â€¢ BRI Vault â€¢ RentCast Market Data*
""")
st.markdown("---")

# Database health metrics
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Vault Properties", f"{stats.get('vault_total', 0):,}")
with col2:
    st.metric("RentCast Leased", f"{stats.get('rentcast_leased', 0):,}")
with col3:
    st.metric("Shannyn's Properties", f"{len(subjects):,}")
with col4:
    st.metric("One-Off Searches", f"{stats.get('one_off_total', 0):,}")
with col5:
    last_dump = stats.get("rentcast_last_dump", "Never")
    st.metric("Last RentCast Dump", str(last_dump))

st.markdown("---")

# ============================================================
# SIDEBAR SEARCH PARAMETERS
# ============================================================
with st.sidebar:
    st.markdown("## âš™ï¸ Search Parameters")

    radius = st.slider(
        "Search Radius (miles)",
        min_value=0.5,
        max_value=5.0,
        value=3.0,
        step=0.5,
        help="Auto-expands to 5 miles if fewer than 5 comps found",
    )

    type_options = {
        "Single Family + Townhomes": ["SINGLE_FAMILY", "TOWNHOUSE", "Single Family", "Townhouse"],
        "Single Family Only": ["SINGLE_FAMILY", "Single Family"],
        "Single Family + Condos": ["SINGLE_FAMILY", "CONDO", "Single Family", "Condo"],
        "All Residential (no apartments)": ["SINGLE_FAMILY", "TOWNHOUSE", "CONDO", "Single Family", "Townhouse", "Condo"],
        "Include Apartments": ["SINGLE_FAMILY", "TOWNHOUSE", "CONDO", "APARTMENT", "Single Family", "Townhouse", "Condo", "Apartment", "Multi-Family"],
        "Condos Only": ["CONDO", "Condo"],
        "Townhomes Only": ["TOWNHOUSE", "Townhouse"],
    }

    selected_type = st.selectbox(
        "Property Types",
        options=list(type_options.keys()),
        index=0,
    )
    property_types = type_options[selected_type]

    use_rentcast = st.checkbox("Include RentCast Data", value=True)
    if use_rentcast:
        st.success(f"âœ… {stats.get('rentcast_leased', 0):,} leased comps")
    else:
        st.warning("RentCast disabled")

# ============================================================
# MAIN TABS
# ============================================================
main_tab1, main_tab2 = st.tabs([
    "ðŸ  Shannyn's Portfolio",
    "ðŸ” One-Off Property Search",
])

# ============================================================
# TAB 1: SHANNYN'S PORTFOLIO
# ============================================================
with main_tab1:
    st.markdown("## Select a Managed Property")

    if not subjects:
        st.error("No subject properties found with coordinates.")
    else:
        property_options = {}
        for s in subjects:
            beds = s.get("bedrooms", "?")
            baths = s.get("bathrooms", "?")
            sqft = int(s.get("living_area", 0)) if s.get("living_area") else 0
            label = f"{s['address']}, {s['city']} | {beds}bd/{baths}ba | {sqft:,} sqft"
            property_options[label] = s

        selected_label = st.selectbox(
            "Choose a property to analyze:",
            options=list(property_options.keys()),
            index=0,
            key="portfolio_selector",
        )

        subject = property_options[selected_label]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Bedrooms", subject.get("bedrooms", "N/A"))
        with col2:
            st.metric("Bathrooms", subject.get("bathrooms", "N/A"))
        with col3:
            sqft_val = int(subject.get("living_area", 0)) if subject.get("living_area") else 0
            st.metric("Square Feet", f"{sqft_val:,}")
        with col4:
            cr = subject.get("current_rent")
            st.metric("Current Rent", f"${int(cr):,}/mo" if cr else "Not Set")

        sub_zillow = make_zillow_url(subject.get("address", ""), subject.get("city", ""), "ID")
        sub_maps = make_google_maps_url(subject.get("address", ""), subject.get("city", ""), "ID")
        link_col1, link_col2 = st.columns(2)
        with link_col1:
            if sub_zillow:
                st.markdown(f"[ðŸ  View on Zillow]({sub_zillow})")
        with link_col2:
            if sub_maps:
                st.markdown(f"[ðŸ“ View on Google Maps]({sub_maps})")

        notes = st.text_area(
            "Additional Notes (optional)",
            placeholder="e.g., 2-car garage, renovated kitchen...",
            height=70,
            key="portfolio_notes",
        )
        if notes:
            subject = dict(subject)
            subject["notes"] = notes

        st.info(
            f"**{subject['address']}, {subject['city']}** | "
            f"Radius: {radius} mi | Types: {selected_type}"
        )

        if st.button(
            "ðŸ¤– Analyze with AI",
            type="primary",
            use_container_width=True,
            key="portfolio_analyze",
        ):
            run_analysis_and_display(subject, radius, property_types, use_rentcast, selected_type)

        if (
            st.session_state.get("done")
            and "result" in st.session_state
            and st.session_state.get("analyzed_address") == subject.get("address")
        ):
            result = st.session_state["result"]
            if result:
                st.markdown("---")
                st.markdown("## Previous Analysis Results")
                st.markdown(result["analysis"])

# ============================================================
# TAB 2: ONE-OFF PROPERTY SEARCH
# ============================================================
with main_tab2:
    st.markdown("## ðŸ” One-Off Property Analysis")
    st.markdown("*Enter any property address for a one-time rental analysis. Perfect for realtors and individual requests.*")

    st.markdown("### Step 1: Enter Property Details")

    with st.form("one_off_form", clear_on_submit=False):
        col1, col2 = st.columns(2)

        with col1:
            oo_address = st.text_input("Street Address *", placeholder="e.g., 1501 N 26th St")
            oo_city = st.text_input("City *", value="Boise")
            oo_state = st.text_input("State *", value="ID")
            oo_zipcode = st.text_input("ZIP Code", placeholder="e.g., 83702")
            oo_requester = st.text_input("Requester Name", placeholder="e.g., John Smith - ABC Realty")

        with col2:
            oo_bedrooms = st.number_input("Bedrooms *", min_value=0.0, max_value=10.0, value=3.0, step=1.0)
            oo_bathrooms = st.number_input("Bathrooms *", min_value=0.0, max_value=10.0, value=2.0, step=0.5)
            oo_sqft = st.number_input("Square Footage *", min_value=0, max_value=10000, value=1500, step=50)
            oo_year_built = st.number_input("Year Built", min_value=1900, max_value=2026, value=2000, step=1)
            oo_property_type = st.selectbox(
                "Property Type",
                options=["Single Family", "Townhouse", "Condo", "Multi-Family", "Apartment"],
                index=0,
            )

        oo_notes = st.text_area(
            "Additional Notes",
            placeholder="e.g., 2-car garage, updated kitchen, pet-friendly...",
            height=70,
        )

        submitted = st.form_submit_button(
            "ðŸ“ Geocode & Analyze Property",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not oo_address or not oo_city or not oo_state:
            st.error("Please fill in Address, City, and State!")
        elif oo_bedrooms <= 0 or oo_bathrooms <= 0 or oo_sqft <= 0:
            st.error("Please enter valid Bedrooms, Bathrooms, and Square Footage!")
        else:
            with st.spinner("Geocoding address and preparing analysis..."):
                saved = save_one_off_search(
                    address=oo_address,
                    city=oo_city,
                    state=oo_state,
                    zipcode=oo_zipcode,
                    bedrooms=oo_bedrooms,
                    bathrooms=oo_bathrooms,
                    living_area=oo_sqft,
                    year_built=int(oo_year_built) if oo_year_built else None,
                    property_type=oo_property_type,
                    notes=oo_notes,
                    requester_name=oo_requester,
                )

            if not saved.get("latitude") or not saved.get("longitude"):
                st.error(
                    "Could not geocode this address. "
                    "Please check the address and try again. "
                    "Make sure the address is in the Treasure Valley area."
                )
            else:
                st.success(
                    f"âœ… Property geocoded! "
                    f"Coordinates: {saved['latitude']:.4f}, {saved['longitude']:.4f}"
                )
                st.session_state["one_off_subject"] = saved
                st.session_state["one_off_ready"] = True

    if st.session_state.get("one_off_ready"):
        subject = st.session_state["one_off_subject"]

        st.markdown("---")
        st.markdown("### Step 2: Review Property Details")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Bedrooms", subject.get("bedrooms", "N/A"))
        with col2:
            st.metric("Bathrooms", subject.get("bathrooms", "N/A"))
        with col3:
            sqft_val = int(subject.get("living_area", 0))
            st.metric("Square Feet", f"{sqft_val:,}")
        with col4:
            yr = subject.get("year_built", "Unknown")
            st.metric("Year Built", yr if yr else "Unknown")

        oo_zillow = make_zillow_url(subject.get("address", ""), subject.get("city", ""), "ID")
        oo_maps = make_google_maps_url(subject.get("address", ""), subject.get("city", ""), "ID")
        link_col1, link_col2 = st.columns(2)
        with link_col1:
            if oo_zillow:
                st.markdown(f"[ðŸ  View on Zillow]({oo_zillow})")
        with link_col2:
            if oo_maps:
                st.markdown(f"[ðŸ“ View on Google Maps]({oo_maps})")

        st.info(
            f"**{subject['address']}, {subject['city']}** | "
            f"Radius: {radius} mi | Types: {selected_type}"
        )

        st.markdown("### Step 3: Run AI Analysis")

        if st.button("ðŸ¤– Analyze with AI", type="primary", use_container_width=True, key="one_off_analyze"):
            run_analysis_and_display(subject, radius, property_types, use_rentcast, selected_type)

        if st.button("ðŸ”„ Start New Search", use_container_width=True, key="one_off_clear"):
            st.session_state["one_off_ready"] = False
            st.session_state["one_off_subject"] = None
            st.rerun()

    st.markdown("---")
    st.markdown("### ðŸ“‹ Recent One-Off Searches")

    recent = get_recent_one_off_searches(limit=10)
    if recent:
        recent_df = pd.DataFrame(recent)
        display_cols = {
            "address": "Address",
            "city": "City",
            "bedrooms": "Beds",
            "bathrooms": "Baths",
            "living_area": "SqFt",
            "property_type": "Type",
            "requester_name": "Requester",
            "created_at": "Date",
        }
        avail = {k: v for k, v in display_cols.items() if k in recent_df.columns}
        display_recent = recent_df[list(avail.keys())].copy()
        display_recent.columns = list(avail.values())
        st.dataframe(display_recent, use_container_width=True)

        recent_options = {
            f"{r['address']}, {r['city']} ({str(r.get('created_at', ''))[:10]})": r
            for r in recent
        }
        selected_recent = st.selectbox(
            "Re-analyze a recent property:",
            options=["-- Select --"] + list(recent_options.keys()),
            key="recent_selector",
        )

        if selected_recent != "-- Select --":
            if st.button("ðŸ”„ Re-Analyze This Property", key="reanalyze_btn"):
                st.session_state["one_off_subject"] = recent_options[selected_recent]
                st.session_state["one_off_ready"] = True
                st.rerun()
    else:
        st.info("No one-off searches yet. Enter a property above to get started!")