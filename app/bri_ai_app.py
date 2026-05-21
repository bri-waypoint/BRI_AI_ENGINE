# app/bri_ai_app.py
# BRI AI Engine - Streamlit Interface
# UPDATED: Two-step comp selection workflow for Shannyn portfolio
#          Step 1: Find Comps - review and select top 15 leased + active
#          Step 2: Generate Report - Claude analyzes selected comps only
# FIXED: Comments saved per property, no bleed-over between properties
# ADDED: Reports saved automatically to database after each analysis
# ADDED: Previous reports tab per property
# One-off searches keep original single-step workflow

import streamlit as st
import pandas as pd
import os
import sys
import urllib.parse
from datetime import datetime

# Fix import paths for Streamlit Cloud
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
sys.path.insert(0, root_dir)
sys.path.insert(0, current_dir)

from config.database import (
    get_subject_properties,
    get_database_stats,
    save_one_off_search,
    get_recent_one_off_searches,
    save_property_notes,
    get_property_notes,
    save_analysis_report,
    get_reports_for_property
)

from bri_ai_engine import (
    get_comparable_properties,
    generate_report,
    analyze_property
)

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="BRI AI Engine",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def make_zillow_url(address, city, state):
    try:
        full = f"{address} {city} {state}"
        encoded = urllib.parse.quote(full)
        return f"https://www.zillow.com/homes/{encoded}_rb/"
    except Exception:
        return None

def make_google_maps_url(address, city, state):
    try:
        full = f"{address}, {city}, {state}"
        encoded = urllib.parse.quote(full)
        return f"https://www.google.com/maps/search/?api=1&query={encoded}"
    except Exception:
        return None

def format_price(val):
    try:
        return f"${int(val):,}"
    except Exception:
        return "N/A"

def format_sqft(val):
    try:
        return f"{int(val):,}"
    except Exception:
        return "N/A"

def show_property_table(props, price_col="Rent/Mo"):
    """Display a read-only property table with links."""
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

    links = []
    for _, row in display_df.iterrows():
        addr = str(row.get("Address", "") or "")
        city = str(row.get("City", "") or "")
        zillow = make_zillow_url(addr, city, "ID")
        maps = make_google_maps_url(addr, city, "ID")
        parts = []
        if zillow:
            parts.append(f'<a href="{zillow}" target="_blank">🏠 Zillow</a>')
        if maps:
            parts.append(f'<a href="{maps}" target="_blank">📍 Map</a>')
        links.append(" | ".join(parts) if parts else "N/A")
    display_df["Links"] = links

    st.write(
        display_df.to_html(escape=False, index=False,
                           classes="dataframe"),
        unsafe_allow_html=True,
    )
    st.caption(f"Showing {len(props)} properties")

def build_selectable_comp_table(props, table_key, price_label="Rent/Mo"):
    """
    Display a sortable, selectable comp table.
    Returns list of selected property dicts.
    Shannyn checks boxes next to the comps she wants to use.
    """
    if not props:
        return []

    # Build display dataframe
    rows = []
    for i, p in enumerate(props):
        rows.append({
            "Select": False,
            "Address": str(p.get("address", "") or ""),
            "City": str(p.get("city", "") or ""),
            "Beds": p.get("bedrooms", ""),
            "Baths": p.get("bathrooms", ""),
            "SqFt": format_sqft(p.get("living_area")),
            price_label: format_price(p.get("current_price")),
            "Date": str(p.get("last_seen_date", "") or "")[:10],
            "Miles": f"{float(p.get('distance_miles') or 0):.2f}",
            "Source": str(p.get("data_source", "") or ""),
            "_index": i
        })

    df = pd.DataFrame(rows)

    # Sort controls
    sort_col = st.selectbox(
        "Sort by:",
        options=["Date", "Miles", "SqFt", "Beds", price_label],
        key=f"sort_{table_key}"
    ) if len(props) > 1 else "Date"

    if sort_col == "Miles":
        df["_sort"] = pd.to_numeric(df["Miles"], errors="coerce")
        df = df.sort_values("_sort")
    elif sort_col == "SqFt":
        df["_sort"] = df["SqFt"].str.replace(",", "").apply(
            pd.to_numeric, errors="coerce"
        )
        df = df.sort_values("_sort", ascending=False)
    elif sort_col == "Beds":
        df["_sort"] = pd.to_numeric(df["Beds"], errors="coerce")
        df = df.sort_values("_sort", ascending=False)
    elif sort_col == price_label:
        df["_sort"] = df[price_label].str.replace(
            "[$,]", "", regex=True
        ).apply(pd.to_numeric, errors="coerce")
        df = df.sort_values("_sort", ascending=False)
    else:
        df = df.sort_values("Date", ascending=False)

    df = df.drop(columns=["_sort"], errors="ignore")

    # Show editable table with checkboxes
    edited = st.data_editor(
        df.drop(columns=["_index"]),
        key=f"editor_{table_key}",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Select": st.column_config.CheckboxColumn(
                "Select",
                help="Check to include in analysis",
                default=False
            )
        }
    )

    # Return selected properties
    selected = []
    for i, row in edited.iterrows():
        if row.get("Select"):
            orig_index = df.iloc[i]["_index"]
            selected.append(props[orig_index])

    return selected

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

st.markdown("# BRI AI Rental Analysis Engine")
st.markdown("*Powered by Claude AI - BRI Vault - RentCast Market Data*")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Vault Properties", f"{stats.get('vault_total', 0):,}")
with col2:
    st.metric("Vault Leased", f"{stats.get('vault_leased', 0):,}")
with col3:
    st.metric("RentCast Leased", f"{stats.get('rentcast_leased', 0):,}")
with col4:
    st.metric("Shannyn Properties", f"{len(subjects):,}")
with col5:
    st.metric("Saved Reports", f"{stats.get('reports_total', 0):,}")

st.markdown("---")

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## Search Parameters")
    radius = st.slider(
        "Search Radius (miles)",
        min_value=0.5, max_value=5.0,
        value=3.0, step=0.5
    )
    type_options = {
        "Single Family + Townhomes": [
            "SINGLE_FAMILY", "TOWNHOUSE",
            "Single Family", "Townhouse"
        ],
        "Single Family Only": [
            "SINGLE_FAMILY", "Single Family"
        ],
        "Single Family + Condos": [
            "SINGLE_FAMILY", "CONDO",
            "Single Family", "Condo"
        ],
        "All Residential (no apartments)": [
            "SINGLE_FAMILY", "TOWNHOUSE", "CONDO",
            "Single Family", "Townhouse", "Condo"
        ],
        "Include Apartments": [
            "SINGLE_FAMILY", "TOWNHOUSE", "CONDO", "APARTMENT",
            "Single Family", "Townhouse", "Condo",
            "Apartment", "Multi-Family"
        ],
        "Condos Only": ["CONDO", "Condo"],
        "Townhomes Only": ["TOWNHOUSE", "Townhouse"],
    }
    selected_type = st.selectbox(
        "Property Types",
        options=list(type_options.keys()),
        index=0
    )
    property_types = type_options[selected_type]
    use_rentcast = st.checkbox("Include RentCast Data", value=True)
    if use_rentcast:
        st.success(
            f"{stats.get('rentcast_leased', 0):,} leased comps available"
        )
    else:
        st.warning("RentCast disabled")

# ============================================================
# MAIN TABS
# ============================================================

main_tab1, main_tab2 = st.tabs([
    "Shannyn Portfolio",
    "One-Off Property Search"
])

# ============================================================
# TAB 1: SHANNYN PORTFOLIO - TWO STEP WORKFLOW
# ============================================================

with main_tab1:
    st.markdown("## Select a Managed Property")

    if not subjects:
        st.error("No subject properties found with coordinates.")
    else:
        # Property selector
        property_options = {}
        for s in subjects:
            beds = s.get("bedrooms", "?")
            baths = s.get("bathrooms", "?")
            sqft = int(s.get("living_area", 0)) if s.get("living_area") else 0
            label = (f"{s['address']}, {s['city']} | "
                     f"{beds}bd/{baths}ba | {sqft:,} sqft")
            property_options[label] = s

        selected_label = st.selectbox(
            "Choose a property to analyze:",
            options=list(property_options.keys()),
            index=0,
            key="portfolio_selector",
        )
        subject = property_options[selected_label]
        property_id = subject.get("id")

        # Detect property change and reset workflow state
        if st.session_state.get("last_property_id") != property_id:
            st.session_state["last_property_id"] = property_id
            st.session_state["comps_ready"] = False
            st.session_state["comp_result"] = None
            st.session_state["report_ready"] = False
            st.session_state["report_result"] = None
            # Load saved notes for this property
            saved = get_property_notes(property_id)
            st.session_state["loaded_notes"] = saved

        # Property details
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
            st.metric("Current Rent",
                      f"${int(cr):,}/mo" if cr else "Not Set")

        # Links
        sub_zillow = make_zillow_url(
            subject.get("address", ""),
            subject.get("city", ""), "ID"
        )
        sub_maps = make_google_maps_url(
            subject.get("address", ""),
            subject.get("city", ""), "ID"
        )
        lc1, lc2 = st.columns(2)
        with lc1:
            if sub_zillow:
                st.markdown(f"[View on Zillow]({sub_zillow})")
        with lc2:
            if sub_maps:
                st.markdown(f"[View on Google Maps]({sub_maps})")

        # Notes - loads saved notes automatically per property
        notes = st.text_area(
            "Property Notes (saved per property)",
            value=st.session_state.get("loaded_notes", ""),
            placeholder="e.g., 2-car garage, renovated kitchen...",
            height=70,
            key=f"notes_{property_id}"
        )

        # Save notes button
        if st.button("💾 Save Notes", key="save_notes_btn"):
            if save_property_notes(property_id, notes):
                st.session_state["loaded_notes"] = notes
                st.success("Notes saved!")
            else:
                st.error("Could not save notes.")

        st.markdown("---")

        # --------------------------------------------------------
        # STEP 1: FIND COMPS
        # --------------------------------------------------------

        st.markdown(
            f"### Step 1 — Find Comps for "
            f"{subject['address']}, {subject['city']}"
        )
        st.info(
            f"Radius: {radius} mi | Types: {selected_type} | "
            f"RentCast: {'On' if use_rentcast else 'Off'}"
        )

        if st.button(
            "🔍 Find Comps",
            type="primary",
            use_container_width=True,
            key="find_comps_btn"
        ):
            with st.spinner(
                "Searching BRI Vault + RentCast... (10-20 seconds)"
            ):
                try:
                    comp_result = get_comparable_properties(
                        subject=subject,
                        radius_miles=radius,
                        property_types=property_types,
                        use_rentcast=use_rentcast
                    )
                    st.session_state["comp_result"] = comp_result
                    st.session_state["comps_ready"] = True
                    st.session_state["report_ready"] = False
                    st.session_state["report_result"] = None
                except Exception as e:
                    st.error(f"Comp search failed: {str(e)}")
                    st.exception(e)

        # --------------------------------------------------------
        # STEP 2: SELECT COMPS
        # --------------------------------------------------------

        if st.session_state.get("comps_ready"):
            comp_result = st.session_state["comp_result"]
            leased_comps = comp_result.get("leased", [])
            active_comps = comp_result.get("active", [])

            if comp_result.get("radius_expanded"):
                st.warning(
                    "Search radius was automatically expanded to "
                    "5 miles due to limited nearby comps."
                )

            total = comp_result.get("total_leased", 0)
            if total >= 10:
                st.success(
                    f"Found {total} recent leased comps — "
                    f"HIGH CONFIDENCE data available"
                )
            elif total >= 5:
                st.warning(
                    f"Found {total} recent leased comps — "
                    f"MEDIUM CONFIDENCE data available"
                )
            else:
                st.error(
                    f"Only {total} recent leased comps found — "
                    f"LOW CONFIDENCE - consider expanding radius"
                )

            st.markdown("---")
            st.markdown("### Step 2 — Select Your Comps")
            st.markdown(
                "Review the top comps below. "
                "**Select at least 3 leased and 3 active** "
                "then click Generate Report."
            )

            comp_tab1, comp_tab2 = st.tabs([
                f"🏠 Leased Comps ({len(leased_comps)} found)",
                f"📋 Active Listings ({len(active_comps)} found)"
            ])

            with comp_tab1:
                if not leased_comps:
                    st.error(
                        "No leased comps found. Try expanding "
                        "your search radius."
                    )
                    selected_leased = []
                else:
                    st.markdown(
                        "Check the boxes next to the leased "
                        "properties you want to include:"
                    )
                    selected_leased = build_selectable_comp_table(
                        leased_comps,
                        table_key="leased",
                        price_label="Leased/Mo"
                    )
                    if selected_leased:
                        st.success(
                            f"✓ {len(selected_leased)} leased "
                            f"comp(s) selected"
                        )
                    else:
                        st.warning("No leased comps selected yet")

            with comp_tab2:
                if not active_comps:
                    st.warning(
                        "No active listings found in this area."
                    )
                    selected_active = []
                else:
                    st.markdown(
                        "Check the boxes next to the active "
                        "listings you want to include:"
                    )
                    selected_active = build_selectable_comp_table(
                        active_comps,
                        table_key="active",
                        price_label="Asking/Mo"
                    )
                    if selected_active:
                        st.success(
                            f"✓ {len(selected_active)} active "
                            f"listing(s) selected"
                        )
                    else:
                        st.warning("No active listings selected yet")

            st.markdown("---")

            # Validate minimum selections
            leased_ok = len(selected_leased) >= 3
            active_ok = len(selected_active) >= 3

            if not leased_ok:
                st.warning(
                    f"Please select at least 3 leased comps "
                    f"(currently {len(selected_leased)} selected)"
                )
            if not active_ok:
                st.warning(
                    f"Please select at least 3 active listings "
                    f"(currently {len(selected_active)} selected)"
                )

            # --------------------------------------------------------
            # STEP 3: GENERATE REPORT
            # --------------------------------------------------------

            st.markdown("### Step 3 — Generate Market Report")

            generate_disabled = not (leased_ok and active_ok)

            if st.button(
                "📊 Generate Market Report",
                type="primary",
                use_container_width=True,
                key="generate_report_btn",
                disabled=generate_disabled
            ):
                # Update subject with current notes
                subject_with_notes = dict(subject)
                subject_with_notes["notes"] = notes

                with st.spinner(
                    "Analyzing with Claude AI... (30-60 seconds)"
                ):
                    try:
                        result = generate_report(
                            subject=subject_with_notes,
                            selected_leased=selected_leased,
                            selected_active=selected_active
                        )
                        result["radius_used"] = comp_result.get(
                            "radius_used", radius
                        )
                        st.session_state["report_result"] = result
                        st.session_state["report_ready"] = True

                        # Save report to database automatically
                        all_selected = selected_leased + selected_active
                        report_id = save_analysis_report(
                            property_id=property_id,
                            property_address=subject.get("address", ""),
                            property_city=subject.get("city", ""),
                            report_text=result["analysis"],
                            selected_comps=all_selected,
                            vault_leased_count=len(result.get(
                                "vault_leased", [])),
                            rentcast_leased_count=len(result.get(
                                "rentcast_leased", [])),
                            total_leased_count=result.get(
                                "total_leased", 0),
                            total_active_count=result.get(
                                "total_active", 0),
                            radius_used=result.get("radius_used", radius),
                            property_notes=notes
                        )
                        if report_id:
                            st.success(
                                f"Report generated and saved! "
                                f"(Report #{report_id})"
                            )
                        else:
                            st.success("Report generated!")
                            st.warning(
                                "Note: Could not save report to database."
                            )

                    except Exception as e:
                        st.error(f"Analysis failed: {str(e)}")
                        st.exception(e)

        # --------------------------------------------------------
        # DISPLAY REPORT
        # --------------------------------------------------------

        if st.session_state.get("report_ready"):
            result = st.session_state["report_result"]
            if result:
                st.markdown("---")
                st.markdown("## Market Report")

                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric("Vault Leased",
                              len(result.get("vault_leased", [])))
                with col2:
                    st.metric("RentCast Leased",
                              len(result.get("rentcast_leased", [])))
                with col3:
                    st.metric("Total Leased",
                              result.get("total_leased", 0))
                with col4:
                    st.metric("Active Listings",
                              result.get("total_active", 0))
                with col5:
                    st.metric("Radius",
                              f"{result.get('radius_used', 3)} mi")

                st.markdown("---")
                st.markdown(result["analysis"])

                # Download button
                addr = subject.get("address", "property")
                export_text = (
                    f"BRI RENTAL ANALYSIS REPORT\n"
                    f"Generated: "
                    f"{datetime.now().strftime('%B %d, %Y %I:%M %p')}\n"
                    f"Property: {subject['address']}, "
                    f"{subject.get('city', '')}\n"
                    f"Search Radius: "
                    f"{result.get('radius_used')} miles\n"
                    f"Notes: {notes}\n\n"
                    f"{'='*60}\n\n"
                    f"{result['analysis']}\n\n"
                    f"{'='*60}\n"
                    f"DATA SUMMARY:\n"
                    f"Vault Leased: "
                    f"{len(result.get('vault_leased', []))}\n"
                    f"RentCast Leased: "
                    f"{len(result.get('rentcast_leased', []))}\n"
                    f"Total Leased Comps: "
                    f"{result.get('total_leased', 0)}\n"
                    f"Total Active Comps: "
                    f"{result.get('total_active', 0)}\n"
                )
                st.download_button(
                    label="⬇️ Download Report",
                    data=export_text,
                    file_name=f"BRI_{addr.replace(' ', '_')}_"
                              f"{datetime.now().strftime('%Y%m%d')}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

        # --------------------------------------------------------
        # PREVIOUS REPORTS TAB
        # --------------------------------------------------------

        if property_id:
            st.markdown("---")
            with st.expander(
                "📁 Previous Reports for This Property", expanded=False
            ):
                prev_reports = get_reports_for_property(
                    property_id, limit=10
                )
                if not prev_reports:
                    st.info(
                        "No previous reports saved for this property yet."
                    )
                else:
                    st.markdown(
                        f"**{len(prev_reports)} saved report(s) found**"
                    )
                    report_options = {
                        f"Report from {r['created_at']} — "
                        f"{r['total_leased_count']} leased comps": r
                        for r in prev_reports
                    }
                    selected_report_label = st.selectbox(
                        "Select a previous report to view:",
                        options=list(report_options.keys()),
                        key="prev_report_selector"
                    )
                    if selected_report_label:
                        prev = report_options[selected_report_label]
                        st.markdown("---")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Leased Comps Used",
                                      prev.get("total_leased_count", 0))
                        with col2:
                            st.metric("Active Comps Used",
                                      prev.get("total_active_count", 0))
                        with col3:
                            st.metric("Radius Used",
                                      f"{prev.get('radius_used', 0)} mi")
                        if prev.get("property_notes"):
                            st.info(
                                f"Notes at time of report: "
                                f"{prev['property_notes']}"
                            )
                        st.markdown(prev["report_text"])

                        # Download previous report
                        dl_text = (
                            f"BRI RENTAL ANALYSIS REPORT\n"
                            f"Generated: {prev['created_at']}\n"
                            f"Property: {subject['address']}, "
                            f"{subject.get('city', '')}\n\n"
                            f"{'='*60}\n\n"
                            f"{prev['report_text']}\n"
                        )
                        st.download_button(
                            label="⬇️ Download This Report",
                            data=dl_text,
                            file_name=f"BRI_{subject['address'].replace(' ', '_')}"
                                      f"_prev_report.txt",
                            mime="text/plain",
                            key="dl_prev_report"
                        )

# ============================================================
# TAB 2: ONE-OFF PROPERTY SEARCH - ORIGINAL WORKFLOW
# ============================================================

with main_tab2:
    st.markdown("## One-Off Property Analysis")
    st.markdown(
        "Enter any property address for a one-time rental analysis."
    )

    st.markdown("### Step 1: Enter Property Details")

    with st.form("one_off_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            oo_address = st.text_input(
                "Street Address",
                placeholder="e.g., 1501 N 26th St"
            )
            oo_city = st.text_input("City", value="Boise")
            oo_state = st.text_input("State", value="ID")
            oo_zipcode = st.text_input(
                "ZIP Code", placeholder="e.g., 83702"
            )
            oo_requester = st.text_input(
                "Requester Name",
                placeholder="e.g., John Smith - ABC Realty"
            )
        with col2:
            oo_bedrooms = st.number_input(
                "Bedrooms",
                min_value=0.0, max_value=10.0,
                value=3.0, step=1.0
            )
            oo_bathrooms = st.number_input(
                "Bathrooms",
                min_value=0.0, max_value=10.0,
                value=2.0, step=0.5
            )
            oo_sqft = st.number_input(
                "Square Footage",
                min_value=0, max_value=10000,
                value=1500, step=50
            )
            oo_year_built = st.number_input(
                "Year Built",
                min_value=1900, max_value=2026,
                value=2000, step=1
            )
            oo_property_type = st.selectbox(
                "Property Type",
                options=[
                    "Single Family", "Townhouse", "Condo",
                    "Multi-Family", "Apartment"
                ],
                index=0
            )

        oo_notes = st.text_area(
            "Additional Notes",
            placeholder="e.g., 2-car garage, updated kitchen...",
            height=70
        )
        submitted = st.form_submit_button(
            "Geocode and Analyze Property",
            type="primary",
            use_container_width=True
        )

    if submitted:
        if not oo_address or not oo_city or not oo_state:
            st.error("Please fill in Address, City, and State!")
        elif oo_bedrooms <= 0 or oo_bathrooms <= 0 or oo_sqft <= 0:
            st.error(
                "Please enter valid Bedrooms, Bathrooms, "
                "and Square Footage!"
            )
        else:
            with st.spinner("Geocoding address..."):
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
                    "Please check and try again."
                )
            else:
                st.success(
                    f"Property geocoded! Coordinates: "
                    f"{saved['latitude']:.4f}, {saved['longitude']:.4f}"
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
            st.metric(
                "Square Feet",
                f"{int(subject.get('living_area', 0)):,}"
            )
        with col4:
            yr = subject.get("year_built", "Unknown")
            st.metric("Year Built", yr if yr else "Unknown")

        oo_zillow = make_zillow_url(
            subject.get("address", ""),
            subject.get("city", ""), "ID"
        )
        oo_maps = make_google_maps_url(
            subject.get("address", ""),
            subject.get("city", ""), "ID"
        )
        lc1, lc2 = st.columns(2)
        with lc1:
            if oo_zillow:
                st.markdown(f"[View on Zillow]({oo_zillow})")
        with lc2:
            if oo_maps:
                st.markdown(f"[View on Google Maps]({oo_maps})")

        st.info(
            f"**{subject['address']}, {subject['city']}** | "
            f"Radius: {radius} mi | Types: {selected_type}"
        )
        st.markdown("### Step 3: Run AI Analysis")

        if st.button(
            "Analyze with AI",
            type="primary",
            use_container_width=True,
            key="one_off_analyze"
        ):
            with st.spinner(
                "Searching + analyzing with Claude AI... "
                "(30-60 seconds)"
            ):
                try:
                    result = analyze_property(
                        subject=subject,
                        radius_miles=radius,
                        property_types=property_types,
                        use_rentcast=use_rentcast,
                    )
                    st.session_state["oo_result"] = result
                    st.session_state["oo_done"] = True
                except Exception as e:
                    st.error(f"Analysis failed: {str(e)}")
                    st.exception(e)

        if st.session_state.get("oo_done"):
            result = st.session_state.get("oo_result")
            if result:
                st.markdown("---")
                st.markdown("## Analysis Results")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Leased",
                              result.get("total_leased", 0))
                with col2:
                    st.metric("Total Active",
                              result.get("total_active", 0))
                with col3:
                    st.metric("Radius",
                              f"{result.get('radius_used', 3)} mi")
                with col4:
                    total = result.get("total_leased", 0)
                    confidence = (
                        "HIGH" if total >= 10
                        else "MEDIUM" if total >= 5
                        else "LOW"
                    )
                    st.metric("Confidence", confidence)

                st.markdown("---")
                st.markdown(result["analysis"])

                addr = subject.get("address", "property")
                export_text = (
                    f"BRI RENTAL ANALYSIS REPORT\n"
                    f"Generated: "
                    f"{datetime.now().strftime('%B %d, %Y %I:%M %p')}\n"
                    f"Property: {subject['address']}, "
                    f"{subject.get('city', '')}\n"
                    f"Search Radius: "
                    f"{result.get('radius_used')} miles\n\n"
                    f"{'='*60}\n\n"
                    f"{result['analysis']}\n\n"
                    f"{'='*60}\n"
                    f"DATA SUMMARY:\n"
                    f"Total Leased Comps: "
                    f"{result.get('total_leased', 0)}\n"
                    f"Total Active Comps: "
                    f"{result.get('total_active', 0)}\n"
                )
                st.download_button(
                    label="⬇️ Download Analysis Report",
                    data=export_text,
                    file_name=f"BRI_{addr.replace(' ', '_')}.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

        if st.button(
            "Start New Search",
            use_container_width=True,
            key="one_off_clear"
        ):
            st.session_state["one_off_ready"] = False
            st.session_state["one_off_subject"] = None
            st.session_state["oo_done"] = False
            st.session_state["oo_result"] = None
            st.rerun()

    st.markdown("---")
    st.markdown("### Recent One-Off Searches")
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
            "created_at": "Date"
        }
        avail = {
            k: v for k, v in display_cols.items()
            if k in recent_df.columns
        }
        display_recent = recent_df[list(avail.keys())].copy()
        display_recent.columns = list(avail.values())
        st.dataframe(display_recent, use_container_width=True)

        recent_options = {
            f"{r['address']}, {r['city']} "
            f"({str(r.get('created_at', ''))[:10]})": r
            for r in recent
        }
        selected_recent = st.selectbox(
            "Re-analyze a recent property:",
            options=["-- Select --"] + list(recent_options.keys()),
            key="recent_selector"
        )
        if selected_recent != "-- Select --":
            if st.button("Re-Analyze This Property",
                         key="reanalyze_btn"):
                st.session_state["one_off_subject"] = (
                    recent_options[selected_recent]
                )
                st.session_state["one_off_ready"] = True
                st.rerun()
    else:
        st.info(
            "No one-off searches yet. "
            "Enter a property above to get started!"
        )
