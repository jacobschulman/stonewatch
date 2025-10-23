import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# Test multiple restaurants
restaurants = [
    {"name": "South Beverly Grill", "merchant_id": "278269", "tz": "America/Los_Angeles"},
    {"name": "Hillstone NYC", "merchant_id": "278278", "tz": "America/New_York"},
    {"name": "Hillstone Santa Monica", "merchant_id": "278267", "tz": "America/Los_Angeles"},  # Guess - verify this ID
    {"name": "East Hampton Grill", "merchant_id": "278240", "tz": "America/New_York"},
]

PARTY_SIZE = 2

for restaurant in restaurants:
    print(f"\n{'='*60}")
    print(f"Testing: {restaurant['name']} (ID: {restaurant['merchant_id']})")
    print(f"{'='*60}")
    
    # Get timestamp for 7 PM tonight in restaurant's timezone
    tz = ZoneInfo(restaurant['tz'])
    tonight = datetime.now(tz).replace(hour=19, minute=0, second=0, microsecond=0)
    timestamp_ms = int(tonight.timestamp() * 1000)
    
    print(f"Time: {tonight.strftime('%Y-%m-%d %I:%M %p %Z')}")
    
    try:
        response = requests.get(
            "https://loyaltyapi.wisely.io/v2/web/reservations/inventory",
            params={
                "merchant_id": restaurant['merchant_id'],
                "party_size": PARTY_SIZE,
                "search_ts": timestamp_ms,
                "show_reservation_types": 1,
                "limit": 3,
            },
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "olo-application-name": "engage-host-public-widget",
                "origin": "https://reservations.getwisely.com",
                "referer": "https://reservations.getwisely.com/"
            },
            timeout=15
        )
        data = response.json()
        print(f"✅ Status: {response.status_code}")
        print(f"Types returned: {len(data.get('types', []))}")
        
        for block in data.get('types', []):
            print(f"  - {block.get('reservation_type_name')}: {len(block.get('times', []))} slots")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")