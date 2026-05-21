# scripts/weekly_vault_update.py
# BRI Automated BrightData Scrape and Vault Update
# CLOUD VERSION - PostgreSQL/Supabase ONLY
# Uses ASYNC /trigger endpoint (no timeout limit)
# Data format: Plain array (no "input" wrapper)
# Fixed: 90-second wait after "ready" before download
# Updated: May 2026
# FIXED: mark_inactive_properties now correctly labels
#        disappearing properties as LEASED and logs
#        inferred leased events to price_history table

import urllib.request
import json
import os
import time
import smtplib
import psycopg2
from email.mime.text import MIMEText
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

BRIGHTDATA_API_TOKEN = os.getenv('BRIGHTDATA_API_TOKEN', '')
BRIGHTDATA_DATASET_ID = os.getenv('BRIGHTDATA_DATASET_ID', '')

ZILLOW_URLS = [
    {"url": "https://www.zillow.com/boise-id-83702/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.69260429977995%2C%22south%22%3A43.57308340022005%2C%22east%22%3A-116.14426818896483%2C%22west%22%3A-116.28695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283702%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94282%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83703/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.69260429977995%2C%22south%22%3A43.57308340022005%2C%22east%22%3A-116.20426818896483%2C%22west%22%3A-116.34695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283703%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94283%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83704/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.69260429977995%2C%22south%22%3A43.57308340022005%2C%22east%22%3A-116.26426818896483%2C%22west%22%3A-116.40695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283704%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94284%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83705/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.64260429977995%2C%22south%22%3A43.52308340022005%2C%22east%22%3A-116.14426818896483%2C%22west%22%3A-116.28695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283705%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94285%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83706/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.64260429977995%2C%22south%22%3A43.52308340022005%2C%22east%22%3A-116.17426818896483%2C%22west%22%3A-116.31695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283706%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94286%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83709/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.60260429977995%2C%22south%22%3A43.48308340022005%2C%22east%22%3A-116.26426818896483%2C%22west%22%3A-116.40695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283709%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94289%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83712/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.64260429977995%2C%22south%22%3A43.52308340022005%2C%22east%22%3A-116.11426818896483%2C%22west%22%3A-116.25695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283712%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94292%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83713/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.69260429977995%2C%22south%22%3A43.57308340022005%2C%22east%22%3A-116.32426818896483%2C%22west%22%3A-116.46695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283713%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94293%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/garden-city-id-83714/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.74260429977995%2C%22south%22%3A43.62308340022005%2C%22east%22%3A-116.20426818896483%2C%22west%22%3A-116.34695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A11%2C%22usersSearchTerm%22%3A%2283714%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94286%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/boise-id-83716/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.60260429977995%2C%22south%22%3A43.48308340022005%2C%22east%22%3A-116.08426818896483%2C%22west%22%3A-116.22695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283716%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94296%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/meridian-id-83642/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.66260429977995%2C%22south%22%3A43.54308340022005%2C%22east%22%3A-116.32426818896483%2C%22west%22%3A-116.46695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283642%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94227%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/eagle-id-83616/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.958609619734624%2C%22south%22%3A43.573813756687365%2C%22east%22%3A-116.00163387792969%2C%22west%22%3A-116.80500912207032%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A11%2C%22usersSearchTerm%22%3A%2283616%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94227%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/eagle-id-83669/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.823784161023084%2C%22south%22%3A43.631261064996195%2C%22east%22%3A-116.30991818896483%2C%22west%22%3A-116.71160581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283669%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94265%2C%22regionType%22%3A7%7D%5D%7D"},
    {"url": "https://www.zillow.com/kuna-id-83634/rentals/?searchQueryState=%7B%22isMapVisible%22%3Atrue%2C%22mapBounds%22%3A%7B%22north%22%3A43.58260429977995%2C%22south%22%3A43.46308340022005%2C%22east%22%3A-116.36426818896483%2C%22west%22%3A-116.50695581103514%7D%2C%22filterState%22%3A%7B%22fr%22%3A%7B%22value%22%3Atrue%7D%2C%22fsba%22%3A%7B%22value%22%3Afalse%7D%2C%22fsbo%22%3A%7B%22value%22%3Afalse%7D%2C%22nc%22%3A%7B%22value%22%3Afalse%7D%2C%22cmsn%22%3A%7B%22value%22%3Afalse%7D%2C%22auc%22%3A%7B%22value%22%3Afalse%7D%2C%22fore%22%3A%7B%22value%22%3Afalse%7D%7D%2C%22isListVisible%22%3Atrue%2C%22mapZoom%22%3A12%2C%22usersSearchTerm%22%3A%2283634%22%2C%22regionSelection%22%3A%5B%7B%22regionId%22%3A94265%2C%22regionType%22%3A7%7D%5D%7D"}
]

# Supabase PostgreSQL Connection
def get_supabase_config():
    return {
        'host': os.getenv('SUPABASE_HOST',
                          'aws-1-us-west-1.pooler.supabase.com'),
        'database': os.getenv('SUPABASE_DB', 'postgres'),
        'user': os.getenv('SUPABASE_USER',
                          'postgres.nftbgxdauxirzmogrydl'),
        'password': os.getenv('SUPABASE_PASSWORD', ''),
        'port': int(os.getenv('SUPABASE_PORT', '5432')),
        'sslmode': 'require',
        'connect_timeout': 30
    }

# SMS Settings
SEND_SMS = True
YOUR_PHONE_NUMBER = "2088670377"
YOUR_CARRIER = "verizon"
GMAIL_ADDRESS = "markflory1@gmail.com"
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', '')
SMS_GATEWAYS = {
    'verizon': 'vtext.com',
    'att': 'txt.att.net',
    'tmobile': 'tmomail.net',
    'sprint': 'messaging.sprintpcs.com'
}

# Logging
LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'logs'
)
os.makedirs(LOG_DIR, exist_ok=True)
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_file = os.path.join(
    LOG_DIR, f'vault_update_{timestamp}.log'
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def log(message):
    """Write to console and log file."""
    print(message)
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                f" - {message}\n"
            )
    except Exception:
        pass

def send_sms(message):
    """Send SMS via email-to-SMS gateway."""
    if not SEND_SMS:
        return
    try:
        gateway = SMS_GATEWAYS.get(YOUR_CARRIER, 'vtext.com')
        sms_email = f"{YOUR_PHONE_NUMBER}@{gateway}"
        msg = MIMEText(message)
        msg['Subject'] = 'BRI Vault Update'
        msg['From'] = GMAIL_ADDRESS
        msg['To'] = sms_email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        log(f"SMS sent to {YOUR_PHONE_NUMBER}")
    except Exception as e:
        log(f"SMS failed: {str(e)}")

def get_db_connection():
    """Get fresh PostgreSQL connection - Supabase only!"""
    return psycopg2.connect(**get_supabase_config())

# ============================================================
# BRIGHTDATA API FUNCTIONS
# ============================================================

def trigger_snapshot():
    """
    Trigger BrightData scrape using ASYNC /trigger endpoint.
    Uses plain array format (no input wrapper).
    Returns snapshot_id for polling.
    """
    log("[STEP 1] Triggering BrightData snapshot (async)...")

    url = (
        f"https://api.brightdata.com/datasets/v3/trigger"
        f"?dataset_id={DATASET_ID}"
        f"&include_errors=true"
        f"&type=discover_new"
        f"&discover_by=url"
        f"&format=json"
    )

    # Plain array format for /trigger endpoint
    payload = json.dumps(ZILLOW_URLS).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Authorization': f'Bearer {API_TOKEN}',
            'Content-Type': 'application/json'
        },
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            log(f"   API Response: {result}")
            snapshot_id = result.get('snapshot_id', '')
            if snapshot_id:
                log(f"   Snapshot triggered: {snapshot_id}")
                return snapshot_id
            else:
                log(f"   No snapshot_id in response!")
                return None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        log(f"   HTTP Error {e.code}: {body[:300]}")
        return None
    except Exception as e:
        log(f"   Trigger error: {str(e)}")
        return None

def check_snapshot_status(snapshot_id):
    """Check snapshot progress status."""
    req = urllib.request.Request(
        f"https://api.brightdata.com/datasets/v3/progress"
        f"/{snapshot_id}",
        headers={'Authorization': f'Bearer {API_TOKEN}'}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('status', 'unknown')
    except Exception as e:
        log(f"   Status check error: {str(e)}")
        return 'unknown'

def wait_for_snapshot(snapshot_id, max_checks=60, interval=60):
    """
    Poll snapshot status until ready.
    Waits 90 seconds after ready before returning
    to allow BrightData to fully package the data.
    """
    log(f"[STEP 2] Waiting for snapshot {snapshot_id}...")

    for check in range(1, max_checks + 1):
        log(f"   Check {check}/{max_checks}: waiting {interval}s...")
        time.sleep(interval)

        state = check_snapshot_status(snapshot_id)
        log(f"   Status: {state}")

        if state == 'ready':
            log(f"   Snapshot ready after {check} checks!")
            log(f"   Waiting 90 seconds for data to finalize...")
            time.sleep(90)
            return True
        elif state in ['failed', 'error']:
            log(f"   Snapshot failed!")
            return False

    log(f"   Timeout after {max_checks} minutes")
    return False

def download_snapshot(snapshot_id):
    """
    Download completed snapshot with retry logic.
    Retries up to 5 times with 30-second waits
    if data is still building.
    """
    log(f"[STEP 3] Downloading snapshot {snapshot_id}...")

    download_url = (
        f"https://api.brightdata.com/datasets/v3/snapshot"
        f"/{snapshot_id}?format=json"
    )

    for attempt in range(1, 6):
        log(f"   Download attempt {attempt}/5...")

        req = urllib.request.Request(
            download_url,
            headers={'Authorization': f'Bearer {API_TOKEN}'}
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode('utf-8')
                log(f"   Response: {len(raw):,} characters")

                try:
                    data = json.loads(raw)

                    # Check if still building
                    if isinstance(data, dict):
                        status = data.get('status', '')
                        if status in ['building', 'starting']:
                            log(f"   Still building: "
                                f"{data.get('message', '')} "
                                f"- waiting 30s...")
                            time.sleep(30)
                            continue

                        # Check for data in wrapper keys
                        for key in ['data', 'records',
                                    'results', 'items']:
                            if (key in data and
                                    isinstance(data[key], list) and
                                    len(data[key]) > 0):
                                log(f"   Got {len(data[key]):,} "
                                    f"records!")
                                return data[key]

                        log(f"   Dict keys: {list(data.keys())}")
                        log(f"   Preview: {raw[:200]}")

                    elif isinstance(data, list):
                        if len(data) > 0:
                            log(f"   Got {len(data):,} records!")
                            return data
                        else:
                            log(f"   Empty list returned")

                except json.JSONDecodeError:
                    # Try JSONL format
                    records = []
                    for line in raw.split('\n'):
                        line = line.strip()
                        if line:
                            try:
                                records.append(json.loads(line))
                            except Exception:
                                pass
                    if records:
                        log(f"   Got {len(records):,} "
                            f"JSONL records!")
                        return records

        except urllib.error.HTTPError as e:
            log(f"   HTTP {e.code}: {e.reason}")
            if attempt < 5:
                log(f"   Waiting 30s before retry...")
                time.sleep(30)
        except Exception as e:
            log(f"   Error: {str(e)[:80]}")
            if attempt < 5:
                time.sleep(30)

    log("   All download attempts failed")
    return []

# ============================================================
# DATABASE IMPORT FUNCTIONS
# ============================================================

def import_to_vault(records, snapshot_date):
    """Import BrightData records to Supabase."""
    log(f"[STEP 4] Importing {len(records):,} records to Vault...")

    new_count = 0
    updated_count = 0
    error_count = 0
    batch_size = 50

    for batch_start in range(0, len(records), batch_size):
        batch = records[batch_start:batch_start + batch_size]

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
        except Exception as e:
            log(f"   DB connection failed: {str(e)}")
            continue

        for record in batch:
            zpid = str(record.get('zpid', '') or '')
            if not zpid or zpid == 'None':
                continue

            try:
                cursor.execute(
                    "SELECT zpid FROM properties "
                    "WHERE zpid = %s::text",
                    (zpid,)
                )
                exists = cursor.fetchone()

                # Handle address whether it comes as a plain
                # string or as a dict from BrightData
                raw_address = record.get('address', '') or ''
                if isinstance(raw_address, dict):
                    address = str(
                        raw_address.get('streetAddress', '') or ''
                    )
                    city = str(
                        raw_address.get('city', '') or
                        record.get('city', '') or ''
                    )
                    state = str(
                        raw_address.get('state', 'ID') or
                        record.get('state', 'ID') or 'ID'
                    )
                    zipcode = str(
                        raw_address.get('zipcode', '') or
                        record.get('zipcode', '') or ''
                    )
                else:
                    address = str(raw_address)
                    city = str(record.get('city', '') or '')
                    state = str(record.get('state', 'ID') or 'ID')
                    zipcode = str(record.get('zipcode', '') or '')
                bedrooms = record.get('bedrooms')
                bathrooms = record.get('bathrooms')
                living_area = record.get('livingArea')
                current_price = record.get('price')
                latitude = record.get('latitude')
                longitude = record.get('longitude')
                hdp_url = str(record.get('hdpUrl', '') or '')
                home_type = str(
                    record.get('homeType', 'SINGLE_FAMILY') or
                    'SINGLE_FAMILY'
                )
                price_history = json.dumps(
                    record.get('priceHistory', [])
                )
                description = str(
                    record.get('description', '') or ''
                )[:500]
                days_on_zillow = record.get('daysOnZillow')
                listing_status = str(
                    record.get('listingStatus', 'ACTIVE') or
                    'ACTIVE'
                )

                if exists:
                    cursor.execute("""
                        UPDATE properties SET
                            address = %s, city = %s,
                            state = %s, zipcode = %s,
                            bedrooms = %s, bathrooms = %s,
                            living_area = %s,
                            current_price = %s,
                            latitude = %s, longitude = %s,
                            hdp_url = %s, home_type = %s,
                            last_seen_date = %s,
                            price_history = %s,
                            description = %s,
                            days_on_zillow = %s,
                            listing_status = %s,
                            is_active = 1
                        WHERE zpid = %s::text
                    """, (
                        address, city, state, zipcode,
                        bedrooms, bathrooms, living_area,
                        current_price, latitude, longitude,
                        hdp_url, home_type, snapshot_date,
                        price_history, description,
                        days_on_zillow, listing_status,
                        zpid
                    ))
                    updated_count += 1
                else:
                    cursor.execute("""
                        INSERT INTO properties (
                            zpid, address, city, state,
                            zipcode, bedrooms, bathrooms,
                            living_area, current_price,
                            latitude, longitude, hdp_url,
                            home_type, data_source,
                            last_seen_date, is_active,
                            price_history, description,
                            days_on_zillow, listing_status
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s,
                            %s, %s
                        )
                    """, (
                        zpid, address, city, state,
                        zipcode, bedrooms, bathrooms,
                        living_area, current_price,
                        latitude, longitude, hdp_url,
                        home_type, 'BrightData',
                        snapshot_date, 1,
                        price_history, description,
                        days_on_zillow, listing_status
                    ))
                    new_count += 1

            except Exception as e:
                log(f"   Error ZPID {zpid}: {str(e)[:80]}")
                error_count += 1
                try:
                    conn.rollback()
                except Exception:
                    pass
                if error_count >= 51:
                    log("   Too many errors - stopping import")
                    break
                continue

        try:
            conn.commit()
            conn.close()
            end = min(batch_start + batch_size, len(records))
            log(f"   Batch saved: records "
                f"{batch_start + 1}-{end}")
        except Exception as e:
            log(f"   Commit error: {str(e)}")

    log(f"Import complete: New {new_count} | "
        f"Updated {updated_count} | Errors {error_count}")
    return new_count, updated_count, error_count

def update_price_history(snapshot_date):
    """Parse and store price history events."""
    log("[STEP 5] Updating price_history table...")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
    except Exception as e:
        log(f"   DB connection failed: {str(e)}")
        return 0, 0

    cursor.execute("""
        SELECT zpid, price_history
        FROM properties
        WHERE price_history IS NOT NULL
        AND price_history != 'null'
        AND price_history != '[]'
        AND price_history != ''
        AND last_seen_date = %s
    """, (snapshot_date,))

    properties = cursor.fetchall()
    log(f"   Processing {len(properties)} properties...")

    inserted = 0
    skipped = 0

    for zpid, price_history_json in properties:
        try:
            history = json.loads(price_history_json)
            if not isinstance(history, list):
                continue

            for event in history:
                date = str(event.get('date', '') or '')[:10]
                event_type = str(event.get('event', '') or '')
                price = event.get('price')
                price_per_sqft = event.get('pricePerSquareFoot')
                price_change_rate = event.get('priceChangeRate')
                source = str(event.get('source', '') or '')
                is_rental = 1 if event.get(
                    'postingIsRental', False
                ) else 0

                if not date or not event_type:
                    continue

                cursor.execute("""
                    SELECT id FROM price_history
                    WHERE zpid = %s::text
                    AND date = %s
                    AND event = %s
                    AND price = %s
                """, (str(zpid), date, event_type, price))

                if cursor.fetchone():
                    skipped += 1
                    continue

                cursor.execute("""
                    INSERT INTO price_history (
                        zpid, date, event, price,
                        price_per_squarefoot,
                        price_change_rate, source,
                        posting_is_rental
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    str(zpid), date, event_type, price,
                    price_per_sqft, price_change_rate,
                    source, is_rental
                ))
                inserted += 1

        except Exception as e:
            log(f"   History error {zpid}: {str(e)[:60]}")
            try:
                conn.rollback()
            except Exception:
                pass
            continue

    try:
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"   Commit error: {str(e)}")

    log(f"Price history: {inserted} new | {skipped} duplicates")
    return inserted, skipped

def mark_inactive_properties(snapshot_date):
    """
    Mark properties not seen in today's scrape as inactive.

    FIXED VERSION - now does three things:
    1. Finds all properties about to go inactive
    2. Logs an inferred LEASED event to price_history for each one
    3. Updates listing_status to LEASED and is_active to 0

    This ensures the comp search can find these properties
    as leased comparables in future searches.
    """
    log("[STEP 6] Marking unseen properties as inactive...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # First get the properties that are about to go inactive
        # so we can log them to price_history before updating
        cursor.execute("""
            SELECT zpid, current_price
            FROM properties
            WHERE last_seen_date != %s
            AND is_active = 1
        """, (snapshot_date,))
        going_inactive = cursor.fetchall()
        log(f"   Found {len(going_inactive):,} properties "
            f"to mark inactive...")

        # Log an inferred LEASED event to price_history
        # for each property going inactive
        leased_logged = 0
        leased_skipped = 0
        for zpid, last_price in going_inactive:
            try:
                # Check if we already logged this transition
                # to avoid duplicates on re-runs
                cursor.execute("""
                    SELECT id FROM price_history
                    WHERE zpid = %s::text
                    AND date = %s
                    AND event = 'Listed as Leased'
                """, (str(zpid), snapshot_date))

                if cursor.fetchone():
                    leased_skipped += 1
                    continue

                # Insert the inferred leased event
                # source = BRI-Inferred so we know it's approximate
                cursor.execute("""
                    INSERT INTO price_history (
                        zpid, date, event, price,
                        price_per_squarefoot,
                        price_change_rate, source,
                        posting_is_rental
                    ) VALUES (
                        %s, %s, 'Listed as Leased', %s,
                        NULL, NULL, 'BRI-Inferred', 1
                    )
                """, (str(zpid), snapshot_date, last_price))
                leased_logged += 1

            except Exception as e:
                log(f"   Price history error {zpid}: "
                    f"{str(e)[:60]}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

        log(f"   Inferred leased events: "
            f"{leased_logged:,} logged | "
            f"{leased_skipped:,} already existed")

        # Now update properties - set LEASED status and is_active=0
        cursor.execute("""
            UPDATE properties
            SET is_active = 0,
                listing_status = 'LEASED'
            WHERE last_seen_date != %s
            AND is_active = 1
        """, (snapshot_date,))
        marked = cursor.rowcount

        conn.commit()
        conn.close()
        log(f"   Marked {marked:,} properties as LEASED/inactive")
        return marked

    except Exception as e:
        log(f"   Error: {str(e)}")
        return 0

def get_vault_stats():
    """Get current vault statistics."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN listing_status = 'LEASED'
                      THEN 1 END) as leased,
                COUNT(CASE WHEN listing_status LIKE '%%ACTIVE%%'
                      THEN 1 END) as active,
                COUNT(*) as total
            FROM properties
            WHERE is_active = 1
        """)
        row = cursor.fetchone()
        conn.close()
        return {
            'leased': row[0] or 0,
            'active': row[1] or 0,
            'total': row[2] or 0
        }
    except Exception as e:
        log(f"   Stats error: {str(e)}")
        return {'leased': 0, 'active': 0, 'total': 0}

# ============================================================
# MAIN EXECUTION
# ============================================================

def main():
    start_time = datetime.now()
    snapshot_date = start_time.strftime('%Y-%m-%d')

    log("=" * 60)
    log("BRI VAULT UPDATE - CLOUD VERSION")
    log("=" * 60)
    log(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Database: Supabase PostgreSQL")
    log(f"API: BrightData async /trigger")
    log(f"Date: {snapshot_date}")
    log("=" * 60)

    send_sms(f"BRI Vault starting... {snapshot_date}")

    # Step 0: Test DB
    log("\n[STEP 0] Testing database connection...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM properties")
        count = cursor.fetchone()[0]
        conn.close()
        log(f"   Connected! Properties: {count:,}")
    except Exception as e:
        log(f"   DB FAILED: {str(e)}")
        send_sms(f"BRI FAILED - DB error: {str(e)[:50]}")
        return False

    # Step 1: Trigger
    snapshot_id = trigger_snapshot()
    if not snapshot_id:
        send_sms("BRI FAILED - Could not trigger snapshot")
        return False

    # Step 2: Wait
    success = wait_for_snapshot(
        snapshot_id, max_checks=60, interval=60
    )
    if not success:
        send_sms("BRI Timeout - Snapshot incomplete")
        return False

    # Step 3: Download
    records = download_snapshot(snapshot_id)
    if not records:
        send_sms("BRI FAILED - No records downloaded")
        return False

    log(f"Downloaded {len(records):,} records")

    # Step 4: Import
    new_count, updated_count, error_count = import_to_vault(
        records, snapshot_date
    )

    # Step 5: Price history
    ph_inserted, ph_skipped = update_price_history(snapshot_date)

    # Step 6: Mark inactive and log leased events
    marked = mark_inactive_properties(snapshot_date)

    # Step 7: Stats
    stats = get_vault_stats()

    # Summary
    duration = (datetime.now() - start_time).seconds // 60
    log("\n" + "=" * 60)
    log("BRI VAULT UPDATE COMPLETE")
    log("=" * 60)
    log(f"Duration: {duration} minutes")
    log(f"Downloaded: {len(records):,} records")
    log(f"New: {new_count:,} | Updated: {updated_count:,} | "
        f"Errors: {error_count}")
    log(f"Price history: {ph_inserted:,} new")
    log(f"Marked inactive/leased: {marked:,}")
    log(f"Vault - Leased: {stats['leased']:,} | "
        f"Active: {stats['active']:,}")
    log("=" * 60)

    send_sms(
        f"BRI Updated\n"
        f"New: {new_count} | Updated: {updated_count}\n"
        f"Leased: {stats['leased']:,} | "
        f"Active: {stats['active']:,}"
    )

    return True

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), '.env'
        )
        load_dotenv(env_path)
        log(f"Loaded .env")
    except ImportError:
        log("Using environment variables directly")

    success = main()
    exit(0 if success else 1)
