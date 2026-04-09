# config/prompt.py
# Shannyn's Master Prompt - The Brain of BRI AI Engine

def safe_int(val, default=0):
    """Safely convert value to int, handling None."""
    try:
        return int(val or default)
    except (TypeError, ValueError):
        return default

def safe_float(val, default=0.0):
    """Safely convert value to float, handling None."""
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default

def safe_str(val, default='N/A'):
    """Safely convert value to string, handling None."""
    if val is None:
        return default
    return str(val)

def format_property_list(properties, label, max_count=25):
    """Format a list of properties for the prompt."""
    if not properties:
        return f"\n**{label}:** None found in search area.\n"

    text = f"\n**{label}:**\n"
    for i, p in enumerate(properties[:max_count], 1):
        source = p.get('data_source', 'Vault')
        text += (
            f"{i}. [{source}] "
            f"{safe_str(p.get('address'))}, "
            f"{safe_str(p.get('city'))} | "
            f"{safe_str(p.get('bedrooms'))}bd/"
            f"{safe_str(p.get('bathrooms'))}ba | "
            f"{safe_int(p.get('living_area')):,} sqft | "
            f"${safe_int(p.get('current_price')):,}/mo | "
            f"Date: {safe_str(p.get('last_seen_date'), 'Unknown')} | "
            f"Distance: {safe_float(p.get('distance_miles')):.2f} mi\n"
        )
    return text

def build_analysis_prompt(subject, nearby_properties,
                          rentcast_data=None, current_date=None):
    """
    Build the complete prompt for Claude to analyze comparables.
    Combines BRI Vault data with stored RentCast data.

    Args:
        subject: Subject property dictionary
        nearby_properties: List of vault properties nearby
        rentcast_data: Dictionary with RentCast leased/active lists
        current_date: Today's date string

    Returns:
        Complete prompt string for Claude
    """
    if current_date is None:
        from datetime import datetime
        current_date = datetime.now().strftime("%B %d, %Y")

    # Separate vault properties by status
    vault_leased = [p for p in nearby_properties
                    if p.get('listing_status') == 'LEASED']
    vault_active = [p for p in nearby_properties
                    if p.get('listing_status') == 'ACTIVE']

    # Get RentCast data
    rc_leased = []
    rc_active = []
    if rentcast_data:
        rc_leased = rentcast_data.get('leased', [])
        rc_active = rentcast_data.get('active', [])

    # Count totals
    total_leased = len(vault_leased) + len(rc_leased)
    total_active = len(vault_active) + len(rc_active)

    # Format property sections
    leased_text = format_property_list(
        vault_leased + rc_leased,
        "LEASED PROPERTIES - Actual Rented Prices (HIGHEST PRIORITY)",
        max_count=25
    )

    active_text = format_property_list(
        vault_active + rc_active,
        "ACTIVE LISTINGS - Current Market Asking Prices (SECONDARY)",
        max_count=15
    )

    # Format subject property safely
    current_rent = subject.get('current_rent')
    rent_display = (f"${safe_int(current_rent):,}/mo"
                   if current_rent else "Not currently set")

    prompt = f"""You are BRI (Boise Rental Intelligence), an expert rental
market analyst specializing in the Treasure Valley, Idaho rental market.
You work for a professional property management company and help determine
accurate rental price ranges for residential properties.

Today's Date: {current_date}

DATA AVAILABLE:
- BRI Vault Leased: {len(vault_leased)} properties
- RentCast Leased: {len(rc_leased)} properties
- Total Leased Comps: {total_leased} properties
- Total Active Listings: {total_active} properties

---

SUBJECT PROPERTY:
- Address: {safe_str(subject.get('address'))}, {safe_str(subject.get('city'))}, {safe_str(subject.get('state'))}
- Bedrooms: {safe_str(subject.get('bedrooms'))}
- Bathrooms: {safe_str(subject.get('bathrooms'))}
- Square Footage: {safe_int(subject.get('living_area')):,} sqft
- Current Rent: {rent_display}
- Notes: {safe_str(subject.get('notes'), 'None provided')}

---

COMPARABLE MARKET DATA:
{leased_text}
{active_text}

---

ANALYSIS CRITERIA (Follow this EXACT priority order):

1. LEASED PROPERTIES = HIGHEST PRIORITY (Gold Standard)
   - [BRI Vault] = scraped from Zillow via Bright Data
   - [RentCast] = verified MLS/Zillow data
   - Leased within 90 days = highest confidence
   - Leased 91-180 days = medium confidence
   - Leased 180+ days = lower confidence

2. LOCATION PROXIMITY (Critical in Boise)
   - Under 0.5 miles = extremely high relevance
   - 0.5-1.0 miles = very high relevance
   - 1.0-2.0 miles = high relevance
   - 2.0-3.0 miles = moderate relevance
   - Over 3.0 miles = low relevance

3. PROPERTY CHARACTERISTICS
   - Bedrooms: within +/- 1 bedroom
   - Bathrooms: within +/- 0.5 bathroom
   - Square footage: within +/- 20%
   - Property type: prefer same type

4. ACTIVE LISTINGS = SECONDARY REFERENCE ONLY
   - Asking prices, NOT actual rented prices
   - Weight at 25-30% vs leased properties
   - High days on market = overpriced

5. SEASONAL CONDITIONS (Boise specific)
   - Peak (May-August): 3-5% stronger
   - Winter (Nov-Feb): 3-5% softer
   - Spring (March-April): warming, increasing demand
   - Fall (Sept-Oct): cooling, stable

---

PRICE ADJUSTMENT GUIDELINES:
- Per bedroom difference: +/- $100-150/month
- Per bathroom difference: +/- $50-75/month
- Per 100 sqft difference: +/- $30-50/month
- Garage: +$75-150/month premium
- Updated kitchen/bath: +$50-100/month
- Distance over 2 miles: reduce weight by 15%

---

Please provide your analysis in this EXACT format:

## BRI Rental Analysis Report
**Property:** {safe_str(subject.get('address'))}, {safe_str(subject.get('city'))}
**Analysis Date:** {current_date}

---

## Recommended Rent Range
### $X,XXX - $X,XXX per month
**Confidence Level:** [High/Medium/Low]
**Confidence Reason:** [One sentence based on data quality]

---

## Key Comparable Properties
[Top 3-5 most relevant comps with explanation]

1. **[Address], [City]** | $X,XXX/mo | [X.XX] mi | [bd/ba/sqft] | [Leased/Active] | [Date] | [Source]
   *Why selected:* [Specific reason]

---

## Market Analysis
[2-3 sentences on current market conditions and reasoning]

---

## Seasonal Pricing Note
[One sentence on current market timing impact]

---

## Caution Flags
[Any concerns, data gaps, or unusual factors]

---

## Pricing Strategy Recommendation
[Specific advice: where to list, when to adjust, high vs low end]

---

CRITICAL RULES:
- ALWAYS provide a RANGE, never a single price
- Leased properties are the gold standard
- Location proximity is the most critical factor
- Be specific about which comps drove your recommendation
- If data is limited, say so clearly"""

    return prompt