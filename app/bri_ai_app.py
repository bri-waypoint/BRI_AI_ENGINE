# app/bri_ai_app.py
# BRI AI Engine - Streamlit Interface
# UPDATED: Fixed inline checkbox + Zillow link table layout
#          One-off search now uses two-step comp selection
#          Bug fix: removed unreachable return in make_google_maps_url

import streamlit as st
import pandas as pd
import os
import sys
import urllib.parse
from datetime import datetime
import folium
from streamlit_folium import st_folium

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

def confidence_display(confidence, round_stopped, radius_used):
    """Show confidence badge with search details."""
    colors = {
        'HIGH': '🟢',
        'GOOD': '🔵',
        'MEDIUM': '🟡',
        'LOW': '🔴'
    }
    icon = colors.get(confidence, '⚪')
    messages = {
        'HIGH': f'HIGH confidence — tight subdivision data '
                f'(Round {round_stopped}, {radius_used} mi radius)',
        'GOOD': f'GOOD confidence — immediate area data '
                f'(Round {round_stopped}, {radius_used} mi radius)',
        'MEDIUM': f'MEDIUM confidence — wider neighborhood '
                  f'(Round {round_stopped}, {radius_used} mi radius)',
        'LOW': f'LOW confidence — limited local data, '
               f'wider search required '
               f'(Round {round_stopped}, {radius_used} mi radius)'
    }
    msg = messages.get(confidence, f'Round {round_stopped}')
    return f"{icon} {msg}"

def render_comp_map(subject, comps, selected_comps, map_key):
    """
    Render an interactive folium map showing:
    - Red star marker for the subject property
    - Numbered blue markers for all comp candidates
    - Numbered green markers for selected comps
    Popups show address, price, beds/baths, distance.
    """
    sub_lat = subject.get("latitude")
    sub_lon = subject.get("longitude")
    if not sub_lat or not sub_lon:
        st.warning("Subject property coordinates not available for map.")
        return

    # Filter comps that have coordinates
    mappable = [p for p in comps if p.get("latitude") and p.get("longitude")]
    if not mappable:
        st.info("No coordinate data available for map display.")
        return

    selected_addresses = {p.get("address", "") for p in selected_comps}

    # Build map centered on subject
    m = folium.Map(
        location=[sub_lat, sub_lon],
        zoom_start=13,
        tiles="OpenStreetMap"
    )

    # Subject property - red star
    folium.Marker(
        location=[sub_lat, sub_lon],
        popup=folium.Popup(
            f"<b>SUBJECT</b><br>{subject.get('address', '')}<br>"
            f"{subject.get('bedrooms','')}bd / {subject.get('bathrooms','')}ba<br>"
            f"{int(subject.get('living_area',0)):,} sqft",
            max_width=200
        ),
        tooltip="📍 Subject Property",
        icon=folium.Icon(color="red", icon="home", prefix="fa")
    ).add_to(m)

    # Comp markers - green if selected, blue if not
    for i, p in enumerate(mappable, start=1):
        is_selected = p.get("address", "") in selected_addresses
        color = "green" if is_selected else "blue"
        price = f"${int(p.get('current_price',0)):,}/mo" if p.get("current_price") else "N/A"
        dist = f"{float(p.get('distance_miles',0)):.2f} mi"
        popup_html = (
            f"<b>#{i} {p.get('address','')}</b><br>"
            f"{p.get('city','')}<br>"
            f"{p.get('bedrooms','')}bd / {p.get('bathrooms','')}ba | "
            f"{int(p.get('living_area',0)):,} sqft<br>"
            f"Rent: {price}<br>"
            f"Distance: {dist}"
        )
        folium.Marker(
            location=[p["latitude"], p["longitude"]],
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"#{i} {p.get('address','')[:30]}",
            icon=folium.Icon(color=color, icon="circle", prefix="fa")
        ).add_to(m)

    st_folium(m, width=None, height=420, key=map_key, returned_objects=[])


def build_selectable_comp_table(props, table_key,
                                price_label="Rent/Mo", map_key=None):
    """
    Display a sortable selectable comp table.
    Each row uses st.columns so checkbox and Zillow link
    are truly inline with all property data on one row.
    Returns list of selected property dicts.
    """
    if not props:
        return []

    # Sort controls
    sort_col = st.selectbox(
        "Sort by:",
        options=["Miles", "Date", "SqFt", "Beds", price_label],
        key=f"sort_{table_key}"
    ) if len(props) > 1 else "Miles"

    # Sort the props list
    def sort_key(p):
        if sort_col == "Miles":
            return float(p.get("distance_miles") or 99)
        elif sort_col == "Date":
            return str(p.get("last_seen_date") or "")
        elif sort_col == "SqFt":
            return -(float(p.get("living_area") or 0))
        elif sort_col == "Beds":
            return -(float(p.get("bedrooms") or 0))
        else:
            return -(float(p.get("current_price") or 0))

    if sort_col == "Date":
        sorted_props = sorted(
            enumerate(props),
            key=lambda x: str(
                x[1].get("last_seen_date") or ""
            ),
            reverse=True
        )
    else:
        sorted_props = sorted(
            enumerate(props),
            key=lambda x: sort_key(x[1])
        )

    # Column header row
    h = st.columns([0.4, 2.8, 0.7, 0.5, 0.5,
                    0.8, 0.9, 0.9, 0.6])
    headers = ["", "Address", "City", "Bed",
               "Bath", "SqFt", price_label, "Date", "Mi"]
    for col, hdr in zip(h, headers):
        col.markdown(f"**{hdr}**")
    st.markdown(
        "<hr style='margin:2px 0 6px 0;border-color:#ddd;'>",
        unsafe_allow_html=True
    )

    selected = []
    for orig_index, p in sorted_props:
        addr = str(p.get("address", "") or "")
        city = str(p.get("city", "") or "")
        zillow_url = make_zillow_url(addr, city, "ID")
        beds = str(p.get("bedrooms", "") or "")
        baths = str(p.get("bathrooms", "") or "")
        sqft = format_sqft(p.get("living_area"))
        price = format_price(p.get("current_price"))
        date = str(p.get("last_seen_date") or "")[:10]
        miles = f"{float(p.get('distance_miles') or 0):.2f}"

        # Shorten address for display if too long
        addr_display = addr[:35] + "…" if len(addr) > 35 else addr

        row = st.columns([0.4, 2.8, 0.7, 0.5, 0.5,
                          0.8, 0.9, 0.9, 0.6])

        with row[0]:
            checked = st.checkbox(
                "",
                key=f"cb_{table_key}_{orig_index}",
                label_visibility="collapsed"
            )
        with row[1]:
            if zillow_url:
                st.markdown(
                    f'{addr_display} '
                    f'<a href="{zillow_url}" '
                    f'target="_blank">🏠</a>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(addr_display)
        with row[2]:
            st.markdown(city)
        with row[3]:
            st.markdown(beds)
        with row[4]:
            st.markdown(baths)
        with row[5]:
            st.markdown(sqft)
        with row[6]:
            st.markdown(price)
        with row[7]:
            st.markdown(date)
        with row[8]:
            st.markdown(miles)

        if checked:
            selected.append(p)

    st.caption(
        f"Showing {len(props)} properties — "
        f"click 🏠 to view on Zillow"
    )
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
st.markdown(
    "*Powered by Claude AI — BRI Vault — RentCast Market Data*"
)
st.markdown("---")

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
    st.metric("Shannyn Properties", f"{len(subjects):,}")
with col5:
    st.metric("Saved Reports",
              f"{stats.get('reports_total', 0):,}")

st.markdown("---")

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## Search Options")
    use_rentcast = st.checkbox("Include RentCast Data", value=True)
    if use_rentcast:
        st.success(
            f"{stats.get('rentcast_leased', 0):,} "
            f"leased comps available"
        )
    else:
        st.warning("RentCast disabled — Vault only")

    st.markdown("---")
    st.markdown("### How Search Works")
    st.markdown(
        "BRI uses a four-round appraisal method:\n\n"
        "🟢 **Round 1** — 1 mile, 15 months\n\n"
        "🔵 **Round 2** — 2 miles, 24 months\n\n"
        "🟡 **Round 3** — 3 miles, 24 months\n\n"
        "🔴 **Round 4** — 5 miles, 24 months\n\n"
        "Search stops when 25+ similar comps found."
    )

# ============================================================
# MAIN TABS
# ============================================================

main_tab1, main_tab2 = st.tabs([
    "Shannyn Portfolio",
    "One-Off Property Search"
])

# ============================================================
# SHARED COMP SELECTION + REPORT DISPLAY LOGIC
# Used by both portfolio and one-off search tabs
# ============================================================

def run_comp_selection_and_report(
    subject, property_id, notes,
    use_rentcast, tab_key,
    save_report=True
):
    """
    Shared two-step workflow used by both tabs.
    tab_key keeps session state separate between tabs.
    save_report=True saves to database (portfolio only).
    """
    # --------------------------------------------------------
    # STEP 1: FIND COMPS
    # --------------------------------------------------------
    st.markdown("### Step 1 — Find Comps")
    st.info(
        f"**{subject.get('address')}, "
        f"{subject.get('city')}** — "
        f"BRI will search using the four-round appraisal "
        f"method, expanding radius until 25+ similar "
        f"properties are found."
    )

    if st.button(
        "🔍 Find Comps",
        type="primary",
        use_container_width=True,
        key=f"find_comps_{tab_key}"
    ):
        with st.spinner(
            "Running appraisal comp search... (15-30 seconds)"
        ):
            try:
                comp_result = get_comparable_properties(
                    subject=subject,
                    use_rentcast=use_rentcast
                )
                st.session_state[
                    f"comp_result_{tab_key}"
                ] = comp_result
                st.session_state[
                    f"comps_ready_{tab_key}"
                ] = True
                st.session_state[
                    f"report_ready_{tab_key}"
                ] = False
                st.session_state[
                    f"report_result_{tab_key}"
                ] = None
            except Exception as e:
                st.error(f"Comp search failed: {str(e)}")
                st.exception(e)

    # --------------------------------------------------------
    # STEP 2: SELECT COMPS
    # --------------------------------------------------------
    if st.session_state.get(f"comps_ready_{tab_key}"):
        comp_result = st.session_state[
            f"comp_result_{tab_key}"
        ]
        leased_comps = comp_result.get("leased", [])
        active_comps = comp_result.get("active", [])
        confidence = comp_result.get("confidence", "LOW")
        round_stopped = comp_result.get("round_stopped", 4)
        radius_used = comp_result.get("radius_used", 5.0)

        st.markdown("---")

        # Confidence display
        conf_msg = confidence_display(
            confidence, round_stopped, radius_used
        )
        if confidence == 'HIGH':
            st.success(conf_msg)
        elif confidence == 'GOOD':
            st.info(conf_msg)
        elif confidence == 'MEDIUM':
            st.warning(conf_msg)
        else:
            st.error(conf_msg)

        st.markdown("### Step 2 — Select Your Comps")
        st.markdown(
            "Review the comps below. "
            "**Select at least 3 leased and 1 active** "
            "then click Generate Report. "
            "Click 🏠 to view any property on Zillow."
        )

        comp_tab1, comp_tab2 = st.tabs([
            f"🏠 Leased Comps ({len(leased_comps)} found)",
            f"📋 Active Listings ({len(active_comps)} found)"
        ])

        with comp_tab1:
            if not leased_comps:
                st.error("No leased comps found.")
                selected_leased = []
            else:
                selected_leased = build_selectable_comp_table(
                    leased_comps,
                    table_key=f"leased_{tab_key}",
                    price_label="Leased/Mo",
                    map_key=f"map_leased_{tab_key}"
                )
                st.markdown("#### 🗺️ Comp Map")
                st.caption("🔴 Subject  |  🔵 Available comp  |  🟢 Selected comp — click any pin for details")
                render_comp_map(
                    subject=subject,
                    comps=leased_comps,
                    selected_comps=selected_leased,
                    map_key=f"folium_leased_{tab_key}"
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
                    "No active listings found. "
                    "Analysis will rely on leased comps only."
                )
                selected_active = []
            else:
                selected_active = build_selectable_comp_table(
                    active_comps,
                    table_key=f"active_{tab_key}",
                    price_label="Asking/Mo",
                    map_key=f"map_active_{tab_key}"
                )
                st.markdown("#### 🗺️ Comp Map")
                st.caption("🔴 Subject  |  🔵 Available comp  |  🟢 Selected comp — click any pin for details")
                render_comp_map(
                    subject=subject,
                    comps=active_comps,
                    selected_comps=selected_active,
                    map_key=f"folium_active_{tab_key}"
                )
                if selected_active:
                    st.success(
                        f"✓ {len(selected_active)} active "
                        f"listing(s) selected"
                    )
                else:
                    st.warning(
                        "No active listings selected yet"
                    )

        st.markdown("---")

        # Validate minimums
        leased_ok = len(selected_leased) >= 3
        active_ok = len(selected_active) >= 1

        if not leased_ok:
            st.warning(
                f"Please select at least 3 leased comps "
                f"(currently {len(selected_leased)} selected)"
            )
        if not active_ok and active_comps:
            st.warning(
                "Please select at least 1 active listing"
            )

        # --------------------------------------------------------
        # STEP 3: GENERATE REPORT
        # --------------------------------------------------------
        st.markdown("### Step 3 — Generate Market Report")

        can_generate = leased_ok and (
            active_ok or not active_comps
        )

        if st.button(
            "📊 Generate Market Report",
            type="primary",
            use_container_width=True,
            key=f"generate_report_{tab_key}",
            disabled=not can_generate
        ):
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
                    result["radius_used"] = radius_used
                    result["confidence"] = confidence
                    result["round_stopped"] = round_stopped
                    st.session_state[
                        f"report_result_{tab_key}"
                    ] = result
                    st.session_state[
                        f"report_ready_{tab_key}"
                    ] = True

                    # Save to database for portfolio only
                    if save_report and property_id:
                        all_selected = (
                            selected_leased + selected_active
                        )
                        report_id = save_analysis_report(
                            property_id=property_id,
                            property_address=subject.get(
                                "address", ""),
                            property_city=subject.get(
                                "city", ""),
                            report_text=result["analysis"],
                            selected_comps=all_selected,
                            vault_leased_count=len(
                                result.get("vault_leased", [])),
                            rentcast_leased_count=len(
                                result.get(
                                    "rentcast_leased", [])),
                            total_leased_count=result.get(
                                "total_leased", 0),
                            total_active_count=result.get(
                                "total_active", 0),
                            radius_used=radius_used,
                            property_notes=notes
                        )
                        if report_id:
                            st.success(
                                f"Report generated and saved! "
                                f"(Report #{report_id})"
                            )
                        else:
                            st.success("Report generated!")
                    else:
                        st.success("Report generated!")

                except Exception as e:
                    st.error(f"Analysis failed: {str(e)}")
                    st.exception(e)

    # --------------------------------------------------------
    # DISPLAY REPORT
    # --------------------------------------------------------
    if st.session_state.get(f"report_ready_{tab_key}"):
        result = st.session_state.get(
            f"report_result_{tab_key}"
        )
        if result:
            st.markdown("---")
            st.markdown("## Market Report")

            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Vault Leased",
                          len(result.get("vault_leased", [])))
            with col2:
                st.metric("RentCast Leased",
                          len(result.get(
                              "rentcast_leased", [])))
            with col3:
                st.metric("Total Leased",
                          result.get("total_leased", 0))
            with col4:
                st.metric("Active Used",
                          result.get("total_active", 0))
            with col5:
                st.metric("Confidence",
                          result.get("confidence", "N/A"))

            st.markdown("---")
            st.markdown(result["analysis"])

            addr = subject.get("address", "property")
            export_text = (
                f"BRI RENTAL ANALYSIS REPORT\n"
                f"Generated: "
                f"{datetime.now().strftime('%B %d, %Y %I:%M %p')}\n"
                f"Property: {subject.get('address', '')}, "
                f"{subject.get('city', '')}\n"
                f"Search Radius: "
                f"{result.get('radius_used')} miles\n"
                f"Confidence: {result.get('confidence')}\n"
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
                file_name=(
                    f"BRI_{addr.replace(' ', '_')}_"
                    f"{datetime.now().strftime('%Y%m%d')}.txt"
                ),
                mime="text/plain",
                use_container_width=True,
                key=f"dl_report_{tab_key}"
            )

# ============================================================
# TAB 1: SHANNYN PORTFOLIO
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
            sqft = int(s.get("living_area", 0)) if s.get(
                "living_area") else 0
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

        # Reset workflow when property changes
        if st.session_state.get("last_property_id") != property_id:
            st.session_state["last_property_id"] = property_id
            st.session_state["comps_ready_portfolio"] = False
            st.session_state["comp_result_portfolio"] = None
            st.session_state["report_ready_portfolio"] = False
            st.session_state["report_result_portfolio"] = None
            saved = get_property_notes(property_id)
            st.session_state["loaded_notes"] = saved

        # Property details
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Bedrooms",
                      subject.get("bedrooms", "N/A"))
        with col2:
            st.metric("Bathrooms",
                      subject.get("bathrooms", "N/A"))
        with col3:
            sqft_val = int(subject.get(
                "living_area", 0)) if subject.get(
                "living_area") else 0
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
                st.markdown(
                    f"[View on Google Maps]({sub_maps})"
                )

        # Notes
        notes = st.text_area(
            "Property Notes (saved per property)",
            value=st.session_state.get("loaded_notes", ""),
            placeholder="e.g., 2-car garage, renovated kitchen, "
                        "renewal pricing, new listing...",
            height=70,
            key=f"notes_{property_id}"
        )

        if st.button("💾 Save Notes", key="save_notes_btn"):
            if save_property_notes(property_id, notes):
                st.session_state["loaded_notes"] = notes
                st.success("Notes saved!")
            else:
                st.error("Could not save notes.")

        st.markdown("---")

        # Run shared two-step workflow
        run_comp_selection_and_report(
            subject=subject,
            property_id=property_id,
            notes=notes,
            use_rentcast=use_rentcast,
            tab_key="portfolio",
            save_report=True
        )

        # --------------------------------------------------------
        # PREVIOUS REPORTS
        # --------------------------------------------------------
        if property_id:
            st.markdown("---")
            with st.expander(
                "📁 Previous Reports for This Property",
                expanded=False
            ):
                prev_reports = get_reports_for_property(
                    property_id, limit=10
                )
                if not prev_reports:
                    st.info(
                        "No previous reports saved for "
                        "this property yet."
                    )
                else:
                    st.markdown(
                        f"**{len(prev_reports)} "
                        f"saved report(s) found**"
                    )
                    report_options = {
                        f"Report from {r['created_at']} — "
                        f"{r['total_leased_count']} "
                        f"leased comps": r
                        for r in prev_reports
                    }
                    selected_report_label = st.selectbox(
                        "Select a previous report to view:",
                        options=list(report_options.keys()),
                        key="prev_report_selector"
                    )
                    if selected_report_label:
                        prev = report_options[
                            selected_report_label
                        ]
                        st.markdown("---")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric(
                                "Leased Comps Used",
                                prev.get(
                                    "total_leased_count", 0)
                            )
                        with col2:
                            st.metric(
                                "Active Comps Used",
                                prev.get(
                                    "total_active_count", 0)
                            )
                        with col3:
                            st.metric(
                                "Radius Used",
                                f"{prev.get('radius_used', 0)}"
                                f" mi"
                            )
                        if prev.get("property_notes"):
                            st.info(
                                f"Notes at time of report: "
                                f"{prev['property_notes']}"
                            )
                        st.markdown(prev["report_text"])

                        dl_text = (
                            f"BRI RENTAL ANALYSIS REPORT\n"
                            f"Generated: {prev['created_at']}\n"
                            f"Property: "
                            f"{subject['address']}, "
                            f"{subject.get('city', '')}\n\n"
                            f"{'='*60}\n\n"
                            f"{prev['report_text']}\n"
                        )
                        st.download_button(
                            label="⬇️ Download This Report",
                            data=dl_text,
                            file_name=(
                                f"BRI_"
                                f"{subject['address'].replace(' ', '_')}"
                                f"_prev_report.txt"
                            ),
                            mime="text/plain",
                            key="dl_prev_report"
                        )

# ============================================================
# TAB 2: ONE-OFF PROPERTY SEARCH
# ============================================================

with main_tab2:
    st.markdown("## One-Off Property Analysis")
    st.markdown(
        "Enter any property address for a one-time "
        "rental analysis."
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
                    "Single Family", "Townhouse", "Condo"
                ],
                index=0
            )

        oo_notes = st.text_area(
            "Additional Notes",
            placeholder="e.g., 2-car garage, updated kitchen, "
                        "renewal pricing, new listing...",
            height=70
        )
        submitted = st.form_submit_button(
            "Geocode Property",
            type="primary",
            use_container_width=True
        )

    if submitted:
        if not oo_address or not oo_city or not oo_state:
            st.error(
                "Please fill in Address, City, and State!"
            )
        elif (oo_bedrooms <= 0 or
              oo_bathrooms <= 0 or
              oo_sqft <= 0):
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
                    year_built=int(
                        oo_year_built
                    ) if oo_year_built else None,
                    property_type=oo_property_type,
                    notes=oo_notes,
                    requester_name=oo_requester,
                )
            if (not saved.get("latitude") or
                    not saved.get("longitude")):
                st.error(
                    "Could not geocode this address. "
                    "Please check and try again."
                )
            else:
                st.success(
                    f"Property geocoded! Coordinates: "
                    f"{saved['latitude']:.4f}, "
                    f"{saved['longitude']:.4f}"
                )
                # Reset one-off workflow state
                st.session_state["oo_subject"] = saved
                st.session_state["oo_ready"] = True
                st.session_state["comps_ready_oneoff"] = False
                st.session_state["comp_result_oneoff"] = None
                st.session_state["report_ready_oneoff"] = False
                st.session_state["report_result_oneoff"] = None

    if st.session_state.get("oo_ready"):
        subject = st.session_state["oo_subject"]
        oo_notes_val = subject.get("notes", "")

        st.markdown("---")
        st.markdown("### Step 2: Review Property Details")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Bedrooms",
                      subject.get("bedrooms", "N/A"))
        with col2:
            st.metric("Bathrooms",
                      subject.get("bathrooms", "N/A"))
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
                st.markdown(
                    f"[View on Google Maps]({oo_maps})"
                )

        st.markdown("---")

        # Run shared two-step workflow
        # save_report=False for one-off searches
        run_comp_selection_and_report(
            subject=subject,
            property_id=None,
            notes=oo_notes_val,
            use_rentcast=use_rentcast,
            tab_key="oneoff",
            save_report=False
        )

        if st.button(
            "🔄 Start New Search",
            use_container_width=True,
            key="one_off_clear"
        ):
            st.session_state["oo_ready"] = False
            st.session_state["oo_subject"] = None
            st.session_state["comps_ready_oneoff"] = False
            st.session_state["comp_result_oneoff"] = None
            st.session_state["report_ready_oneoff"] = False
            st.session_state["report_result_oneoff"] = None
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
            options=["-- Select --"] + list(
                recent_options.keys()
            ),
            key="recent_selector"
        )
        if selected_recent != "-- Select --":
            if st.button("Re-Analyze This Property",
                         key="reanalyze_btn"):
                reanalyze = recent_options[selected_recent]
                st.session_state["oo_subject"] = reanalyze
                st.session_state["oo_ready"] = True
                st.session_state["comps_ready_oneoff"] = False
                st.session_state["comp_result_oneoff"] = None
                st.session_state["report_ready_oneoff"] = False
                st.session_state["report_result_oneoff"] = None
                st.rerun()
    else:
        st.info(
            "No one-off searches yet. "
            "Enter a property above to get started!"
        )
