# config/prompt.py
# Shannyn's Master Prompt - The Brain of BRI AI Engine
# Updated: Enforces 15-month recency, distance, then similarity
# Clean formatting - no markdown symbols that cause spacing issues

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

def format_property_list(properties, label, max_count=30):
    """
    Format a list of properties for the prompt.
    Uses plain text formatting to avoid spacing issues.
    """
    if not properties:
        return f"\n{label}: None found in search area.\n"

    text = f"\n{label}:\n"
    for i, p in enumerate(properties[:max_count], 1):
        source = p.get('data_source', 'Vault')
        beds = safe_str(p.get('bedrooms'))
        baths = safe_str(p.get('bathrooms'))
        sqft = safe_int(p.get('living_area'))
        price = safe_int(p.get('current_price'))
        dist = safe_float(p.get('distance_miles'))
        addr = safe_str(p.get('address'))
        city = safe_str(p.get('city'))
        date = safe_str(p.get('last_seen_date'), 'Unknown')

        text += (
            f"{i}. [{source}] {addr}, {city} - "
            f"{beds} bed / {baths} bath / {sqft:,} sqft - "
            f"${price:,} per month - "
            f"Leased: {date} - "
            f"{dist:.2f} miles away\n"
        )
    return text

def format_active_list(properties, label, max_count=15):
    """Format active listings separately."""
    if not properties:
        return f"\n{label}: None found in search area.\n"

    text = f"\n{label}:\n"
    for i, p in enumerate(properties[:max_count], 1):
        source = p.get('data_source', 'Vault')
        beds = safe_str(p.get('bedrooms'))
        baths = safe_str(p.get('bathrooms'))
        sqft = safe_int(p.get('living_area'))
        price = safe_int(p.get('current_price'))
        dist = safe_float(p.get('distance_miles'))
        addr = safe_str(p.get('address'))
        city = safe_str(p.get('city'))
        dom = safe_str(p.get('days_on_market'), 'Unknown')

        text += (
            f"{i}. [{source}] {addr}, {city} - "
            f"{beds} bed / {baths} bath / {sqft:,} sqft - "
            f"${price:,} per month asking - "
            f"{dom} days on market - "
            f"{dist:.2f} miles away\n"
        )
    return text

def build_analysis_prompt(subject, nearby_properties,
                          rentcast_data=None, current_date=None):
    """
    Build the complete prompt for Claude to analyze comparables.
    Enforces: Recency (15mo) first, Distance second, Similarity third.
    """
    if current_date is None:
        from datetime import datetime
        current_date = datetime.now().strftime("%B %d, %Y")

    # Separate vault properties by status
    vault_leased = [p for p in nearby_properties
                    if p.get('listing_status') == 'LEASED']
    vault_active = [p for p in nearby_properties
                    if 'ACTIVE' in str(
                        p.get('listing_status', '')).upper()]

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
        "LEASED PROPERTIES - Actual Rented Prices - HIGHEST PRIORITY",
        max_count=30
    )

    active_text = format_active_list(
        vault_active + rc_active,
        "ACTIVE LISTINGS - Current Market Asking Prices - SECONDARY ONLY",
        max_count=15
    )

    # Format subject property
    current_rent = subject.get('current_rent')
    rent_display = (f"${safe_int(current_rent):,} per month"
                   if current_rent else "Not currently set")

    subject_address = safe_str(subject.get('address'))
    subject_city = safe_str(subject.get('city'))
    subject_state = safe_str(subject.get('state'))
    subject_beds = safe_str(subject.get('bedrooms'))
    subject_baths = safe_str(subject.get('bathrooms'))
    subject_sqft = safe_int(subject.get('living_area'))
    subject_notes = safe_str(subject.get('notes'), 'None provided')

    prompt = f"""You are BRI, the Boise Rental Intelligence analyst.
You are an expert in the Treasure Valley, Idaho rental market.
You work for a professional property management company.
Your job is to determine accurate rental price ranges for residential properties.

Today's Date: {current_date}

DATA AVAILABLE FOR THIS ANALYSIS:
BRI Vault Leased Properties within 15 months: {len(vault_leased)}
RentCast Verified Leased Properties within 15 months: {len(rc_leased)}
Total Recent Leased Comparables: {total_leased}
Total Active Listings: {total_active}

SUBJECT PROPERTY:
Address: {subject_address}, {subject_city}, {subject_state}
Bedrooms: {subject_beds}
Bathrooms: {subject_baths}
Square Footage: {subject_sqft:,} sqft
Current Rent: {rent_display}
Notes: {subject_notes}

COMPARABLE MARKET DATA:
{leased_text}
{active_text}

ANALYSIS RULES - YOU MUST FOLLOW THESE IN EXACT ORDER:

RULE 1 - RECENCY IS THE MOST IMPORTANT FILTER:
Only use leased properties from the last 15 months as comparables.
The data provided has already been filtered to the last 15 months.
Within those, prioritize by how recently they leased:
Leased within 90 days is the highest priority - use these first.
Leased 91 to 180 days is high priority - use these second.
Leased 181 days to 15 months is medium priority - use only if needed.
Never reference or use a property leased more than 15 months ago.
If you see a lease date before {current_date[:4]}, treat it with low weight.

RULE 2 - DISTANCE IS THE SECOND FILTER:
After filtering by recency, prioritize by proximity.
Under 0.5 miles means extremely high relevance.
0.5 to 1.0 miles means very high relevance.
1.0 to 2.0 miles means high relevance.
2.0 to 3.0 miles means moderate relevance.
Over 3.0 miles means low relevance - only use if nothing closer exists.

RULE 3 - PROPERTY SIMILARITY IS THE THIRD FILTER:
After recency and distance, match property characteristics.
Bedrooms must be within plus or minus 1 bedroom.
Bathrooms must be within plus or minus 0.5 bathroom.
Square footage should ideally be within plus or minus 20 percent.
Prefer the same property type when possible.

RULE 4 - ACTIVE LISTINGS ARE SECONDARY REFERENCE ONLY:
Active listings show current market competition and asking prices.
They are NOT actual rented prices.
Weight active listings at about 25 percent compared to leased properties.
High days on market suggests the property may be overpriced.

RULE 5 - SEASONAL CONDITIONS FOR BOISE:
Peak season May through August means market is 3 to 5 percent stronger.
Winter November through February means market is 3 to 5 percent softer.
Spring March and April means market is warming with increasing demand.
Fall September and October means market is cooling with stable pricing.

PRICE ADJUSTMENT GUIDELINES:
Per bedroom difference: plus or minus 100 to 150 dollars per month.
Per bathroom difference: plus or minus 50 to 75 dollars per month.
Per 100 square feet difference: plus or minus 30 to 50 dollars per month.
Garage included: plus 75 to 150 dollars per month premium.
Distance over 2 miles: reduce the weight of that comparable by 15 percent.

FORMATTING RULES - VERY IMPORTANT:
Write in plain clear English with no special characters.
Put a space between every single word without exception.
Never combine two words without a space between them.
Use complete grammatical sentences throughout your response.
Do not use asterisks, pound signs, or pipe characters anywhere.
Write dollar amounts clearly such as 2,100 dollars per month.
Write distances clearly such as 0.35 miles away.
Write dates clearly such as January 2026 or October 2025.

Please write your complete analysis using exactly this structure:

BRI RENTAL ANALYSIS REPORT
Property: {subject_address}, {subject_city}
Analysis Date: {current_date}

RECOMMENDED RENT RANGE
Recommended Range: [dollar amount] to [dollar amount] per month
Confidence Level: [High, Medium, or Low]
Confidence Reason: [One clear sentence explaining why you chose this confidence level based on the quality and quantity of recent comparable data available]

KEY COMPARABLE PROPERTIES
[Select your top 5 to 15 most relevant comparables following Rules 1, 2, and 3 in that exact order. Recent and close properties first.]

1. [Address, City] - [price] per month - [distance] miles away - [beds] bed / [baths] bath / [sqft] sqft - Leased [month and year] - [Source]
   Why selected: [Explain specifically why this property is a good comparable, mentioning its recency, proximity, and similarity to the subject property]

2. [Address, City] - [price] per month - [distance] miles away - [beds] bed / [baths] bath / [sqft] sqft - Leased [month and year] - [Source]
   Why selected: [Explain specifically why this property is a good comparable]

3. [Address, City] - [price] per month - [distance] miles away - [beds] bed / [baths] bath / [sqft] sqft - Leased [month and year] - [Source]
   Why selected: [Explain specifically why this property is a good comparable]

[Add 4th and 5th comparable if strong recent data exists]

MARKET ANALYSIS
[Write 2 to 3 complete sentences explaining current market conditions in this specific neighborhood, what the recent leased data tells us about rental demand, and the reasoning behind your recommended price range. Focus on data from the last 6 months when possible.]

SEASONAL PRICING NOTE
[Write one complete sentence about how the current time of year affects pricing strategy for this specific property in the Boise market.]

CAUTION FLAGS
[List any concerns such as limited recent data, wide price variance in comps, unusual market conditions, or property-specific factors. If there are no concerns, write: No significant caution flags identified for this property.]

PRICING STRATEGY RECOMMENDATION
[Write one paragraph with specific actionable advice for Shannyn. Tell her exactly where in the range to list the property initially. Explain when she should consider adjusting the price. Describe what factors would justify pricing at the high end versus the low end of the range. Base this advice on the most recent comparable data available.]

FINAL REMINDERS FOR YOUR RESPONSE:
Always provide a price range and never a single price point.
Recent leased properties are the gold standard - prioritize them above everything else.
Location proximity is the second most critical factor after recency.
Be specific about which comparable properties most influenced your recommendation.
If recent data within 15 months is limited, say so clearly in your caution flags.
Every word must be separated by a space with no words running together.
"""

    return prompt