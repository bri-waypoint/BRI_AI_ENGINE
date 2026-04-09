# app/bri_ai_app.py
# BRI AI Engine - Streamlit Interface for Shannyn
# Clean, intuitive interface combining Vault + RentCast data

import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.database import get_subject_properties, get_database_stats
from app.bri_ai_engine import analyze_property

# Page config
st.set_page_config(
    page_title="BRI AI Engine",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Header
st.markdown("""
# 🏠 BRI AI Rental Analysis Engine
*Powered by Claude AI • BRI Vault • RentCast Market Data*
""")
st.markdown("---")

# Database stats in header
@st.cache_data(ttl=300)
def load_stats():
    return get_database_stats()

@st.cache_data(ttl=300)
def load_subjects():
    return get_subject_properties()

stats = load_stats()
subjects = load_subjects()

# Show database health
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Vault Properties",
              f"{stats.get('vault_total', 0):,}")
with col2:
    st.metric("Vault Leased",
              f"{stats.get('vault_leased', 0):,}")
with col3:
    st.metric("RentCast Leased",
              f"{stats.get('rentcast_leased', 0):,}")
with col4:
    st.metric("RentCast Active",
              f"{stats.get('rentcast_active', 0):,}")
with col5:
    last_dump = stats.get('rentcast_last_dump', 'Never')
    st.metric("Last RentCast Dump", str(last_dump))

st.markdown("---")

if not subjects:
    st.error("No subject properties found with coordinates.")
    st.stop()

# ============================================================
# STEP 1: SELECT PROPERTY
# ============================================================
st.markdown("## Step 1: Select Subject Property")

property_options = {}
for s in subjects:
    beds = s.get('bedrooms', '?')
    baths = s.get('bathrooms', '?')
    sqft = int(s.get('living_area', 0)) if s.get('living_area') else 0
    label = (f"{s['address']}, {s['city']} | "
             f"{beds}bd/{baths}ba | {sqft:,} sqft")
    property_options[label] = s

selected_label = st.selectbox(
    "Choose a property to analyze:",
    options=list(property_options.keys()),
    index=0
)

subject = property_options[selected_label]

# Property metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Bedrooms", subject.get('bedrooms', 'N/A'))
with col2:
    st.metric("Bathrooms", subject.get('bathrooms', 'N/A'))
with col3:
    sqft_val = int(subject.get('living_area', 0)) \
               if subject.get('living_area') else 0
    st.metric("Square Feet", f"{sqft_val:,}")
with col4:
    cr = subject.get('current_rent')
    st.metric("Current Rent",
              f"${int(cr):,}/mo" if cr else "Not Set")

# ============================================================
# STEP 2: SEARCH PARAMETERS
# ============================================================
st.markdown("---")
st.markdown("## Step 2: Search Parameters")

col1, col2, col3 = st.columns(3)

with col1:
    radius = st.slider(
        "Search Radius (miles)",
        min_value=0.5, max_value=5.0,
        value=3.0, step=0.5,
        help="BRI auto-expands to 5 miles if fewer than 5 leased comps found"
    )

with col2:
    type_options = {
        "Single Family + Townhomes": [
            'SINGLE_FAMILY', 'TOWNHOUSE',
            'Single Family', 'Townhouse'
        ],
        "Single Family Only": [
            'SINGLE_FAMILY', 'Single Family'
        ],
        "Single Family + Condos": [
            'SINGLE_FAMILY', 'CONDO',
            'Single Family', 'Condo'
        ],
        "All Residential (no apartments)": [
            'SINGLE_FAMILY', 'TOWNHOUSE', 'CONDO',
            'Single Family', 'Townhouse', 'Condo'
        ],
        "Include Apartments": [
            'SINGLE_FAMILY', 'TOWNHOUSE', 'CONDO',
            'APARTMENT', 'Single Family', 'Townhouse',
            'Condo', 'Apartment', 'Multi-Family'
        ],
        "Condos Only": ['CONDO', 'Condo'],
        "Townhomes Only": ['TOWNHOUSE', 'Townhouse']
    }

    selected_type = st.selectbox(
        "Property Types",
        options=list(type_options.keys()),
        index=0
    )
    property_types = type_options[selected_type]

with col3:
    use_rentcast = st.checkbox(
        "Include RentCast Data",
        value=True,
        help=f"Adds {stats.get('rentcast_leased', 0):,} "
             f"verified leased properties to analysis"
    )
    if use_rentcast:
        st.success(f"✅ {stats.get('rentcast_leased', 0):,} "
                   f"leased comps available")
    else:
        st.warning("RentCast disabled")

# Optional notes
notes = st.text_area(
    "Property Notes (optional)",
    placeholder="e.g., 2-car garage, renovated kitchen, "
                "pet-friendly, fenced yard, new HVAC...",
    height=70
)

if notes:
    subject = dict(subject)
    subject['notes'] = notes

# ============================================================
# STEP 3: ANALYZE
# ============================================================
st.markdown("---")
st.markdown("## Step 3: Run AI Analysis")

# Summary info box
rc_status = (f"RentCast: ✅ {stats.get('rentcast_leased', 0):,} "
             f"leased comps"
             if use_rentcast else "RentCast: ❌ Disabled")

st.info(
    f"**{subject['address']}, {subject['city']}** | "
    f"Radius: {radius} mi | "
    f"Types: {selected_type} | "
    f"{rc_status}"
)

if st.button("🤖 Analyze with AI",
             type="primary",
             use_container_width=True):

    with st.spinner(
        "Searching BRI Vault + RentCast data and "
        "analyzing with Claude AI... (30-60 seconds)"
    ):
        try:
            result = analyze_property(
                subject=subject,
                radius_miles=radius,
                property_types=property_types,
                use_rentcast=use_rentcast
            )
            st.session_state['result'] = result
            st.session_state['done'] = True

        except Exception as e:
            st.error(f"Analysis failed: {str(e)}")
            st.exception(e)
            st.stop()

# ============================================================
# DISPLAY RESULTS
# ============================================================
if st.session_state.get('done') and 'result' in st.session_state:
    result = st.session_state['result']

    st.markdown("---")

    # Results stats
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Vault Leased",
                  len(result.get('vault_leased', [])))
    with col2:
        st.metric("RentCast Leased",
                  len(result.get('rentcast_leased', [])))
    with col3:
        st.metric("Total Leased Comps",
                  result.get('total_leased', 0))
    with col4:
        st.metric("Active Listings",
                  result.get('total_active', 0))
    with col5:
        st.metric("Radius Used",
                  f"{result.get('radius_used', 3)} mi")

    # Confidence indicator
    total_leased = result.get('total_leased', 0)
    if total_leased >= 10:
        st.success(f"✅ HIGH CONFIDENCE - {total_leased} "
                   f"leased comps found")
    elif total_leased >= 5:
        st.warning(f"⚠️ MEDIUM CONFIDENCE - {total_leased} "
                   f"leased comps found")
    else:
        st.error(f"❌ LOW CONFIDENCE - Only {total_leased} "
                 f"leased comps found")

    # AI Analysis output
    st.markdown("---")
    st.markdown(result['analysis'])

    # Data tables
    st.markdown("---")
    st.markdown("### Comparable Property Data")

    tab1, tab2, tab3, tab4 = st.tabs([
        f"🔑 Vault Leased ({len(result.get('vault_leased', []))})",
        f"🏆 RentCast Leased ({len(result.get('rentcast_leased', []))})",
        f"📊 Vault Active ({len(result.get('vault_active', []))})",
        f"📋 RentCast Active ({len(result.get('rentcast_active', []))})"
    ])

    def show_table(props, price_col="Rent/Mo"):
        if not props:
            st.info("No properties in this category.")
            return
        df = pd.DataFrame(props)
        cols = {
            'address': 'Address',
            'city': 'City',
            'bedrooms': 'Beds',
            'bathrooms': 'Baths',
            'living_area': 'SqFt',
            'current_price': price_col,
            'last_seen_date': 'Date',
            'distance_miles': 'Miles',
            'home_type': 'Type',
            'data_source': 'Source'
        }
        avail = {k: v for k, v in cols.items()
                 if k in df.columns}
        display = df[list(avail.keys())].copy()
        display.columns = list(avail.values())
        st.dataframe(display, use_container_width=True)

    with tab1:
        st.caption("Properties from BRI Vault (Bright Data/Zillow)")
        show_table(result.get('vault_leased', []), "Leased/Mo")

    with tab2:
        st.caption("Verified leased properties from RentCast")
        show_table(result.get('rentcast_leased', []), "Leased/Mo")

    with tab3:
        st.caption("Active listings from BRI Vault")
        show_table(result.get('vault_active', []), "Asking/Mo")

    with tab4:
        st.caption("Active listings from RentCast")
        show_table(result.get('rentcast_active', []), "Asking/Mo")

    # Export
    st.markdown("---")
    export_text = f"""BRI RENTAL ANALYSIS REPORT
Generated: {datetime.now().strftime("%B %d, %Y %I:%M %p")}
Property: {subject['address']}, {subject['city']}
Search Radius: {result.get('radius_used')} miles
Property Types: {selected_type}

{'='*60}

{result['analysis']}

{'='*60}
DATA SUMMARY:
Vault Leased: {len(result.get('vault_leased', []))}
RentCast Leased: {len(result.get('rentcast_leased', []))}
Total Leased Comps: {result.get('total_leased', 0)}
Total Active Comps: {result.get('total_active', 0)}
Search Radius: {result.get('radius_used')} miles
"""

    st.download_button(
        label="📄 Download Analysis Report",
        data=export_text,
        file_name=f"BRI_{subject['address'].replace(' ', '_')}.txt",
        mime="text/plain",
        use_container_width=True
    )