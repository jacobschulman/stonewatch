# vip_watcher.py - VIP-targeted table monitoring for specific date/time windows
import os, time, json, requests, random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# GitHub Actions metadata (for run tracking)
GITHUB_RUN_ID  = os.getenv("GITHUB_RUN_ID", "")
GITHUB_SERVER  = os.getenv("GITHUB_SERVER_URL", "https://github.com")
GITHUB_REPO    = os.getenv("GITHUB_REPOSITORY", "")

# ---- Config via ENV ----
MERCHANT_ID = os.getenv("MERCHANT_ID", "278278")
RESTAURANT_NAME = os.getenv("RESTAURANT_NAME", "Hillstone NYC")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
NOTIFICATION_PREFIX = os.getenv("NOTIFICATION_PREFIX", "🔥💎 VIP TABLE ALERT 💎🔥")
STEP_MIN = int(os.getenv("STEP_MIN", "15"))
LINK_BASE = os.getenv("LINK_BASE", "https://example.com")

# Randomization (anti-detection)
RANDOMIZE_DELAY = os.getenv("RANDOMIZE_DELAY", "true").lower() == "true"
RANDOM_STAGGER_MS = os.getenv("RANDOM_STAGGER_MS", "50,200")
try:
    stagger_min, stagger_max = map(int, RANDOM_STAGGER_MS.split(","))
    RANDOM_STAGGER = (stagger_min, stagger_max)
except:
    RANDOM_STAGGER = (50, 200)

# Safety limits
MAX_CHECKS_PER_HOUR = int(os.getenv("MAX_CHECKS_PER_HOUR", "120"))

# Testing
TEST_NOTIFICATION = os.getenv("TEST_NOTIFICATION", "false").lower() == "true"

# Notifications
PUSHOVER_USER = os.getenv("PUSHOVER_USER")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
PUSHOVER_SOUND = os.getenv("PUSHOVER_SOUND", "magic")
PUSHOVER_PRIORITY = os.getenv("PUSHOVER_PRIORITY", "1")
PUSHOVER_URL_TITLE_DEFAULT = "Book VIP Table NOW!"

# Gist state (VIP-specific, separate from base monitor)
GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
STATE_FILENAME = f"vip_{MERCHANT_ID}.json"

# VIP Windows config
VIP_WINDOWS_RAW = os.getenv("VIP_WINDOWS", "").strip()

# Supabase (optional - for run tracking)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ---- Constants ----
NYC = ZoneInfo(TIMEZONE)
BASE_URL = "https://loyaltyapi.wisely.io/v2/web/reservations/inventory"
RES_TYPE_ID = {"Dinner": 1695, "Lunch": 1862}

# ---- Helper Functions (reused from watcher.py) ----
def to_epoch_ms(dt_local: datetime) -> int:
    return int(dt_local.timestamp() * 1000)

def parse_hm(hm: str):
    h, m = map(int, hm.split(":")); return h, m

def probe(ts_ms: int, party: int, type_id: int) -> dict:
    """Query Wisely API for available slots"""
    r = requests.get(
        BASE_URL,
        params={
            "merchant_id": MERCHANT_ID,
            "party_size": party,
            "reservation_type_id": type_id,
            "search_ts": ts_ms,
            "show_reservation_types": 1,
            "limit": 3,
        },
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "olo-application-name": "engage-host-public-widget",
            "origin": "https://reservations.getwisely.com",
            "referer": "https://reservations.getwisely.com/"
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def format_when(iso_time: str|None, label: str|None, probed: datetime):
    """Format slot time for display"""
    if iso_time:
        try:
            dt = datetime.fromisoformat(iso_time.replace("Z","+00:00")).astimezone(NYC)
            return dt.strftime("%a %b %d"), dt.strftime("%-I:%M %p")
        except Exception:
            pass
    lbl = (label or "").strip()
    if lbl:
        try:
            t_only = datetime.strptime(lbl.upper(), "%I:%M %p")
            dt = probed.replace(hour=t_only.hour, minute=t_only.minute, second=0, microsecond=0)
            return dt.strftime("%a %b %d"), dt.strftime("%-I:%M %p")
        except Exception:
            return probed.strftime("%a %b %d"), lbl
    return probed.strftime("%a %b %d"), "(time?)"

def determine_service_type(dt_local: datetime) -> tuple[str, int] | None:
    """Determine if time falls in Lunch or Dinner window"""
    hour = dt_local.hour
    minute = dt_local.minute
    time_val = hour * 60 + minute

    # Dinner: 5:00 PM - 10:15 PM (17:00 - 22:15)
    dinner_start = 17 * 60  # 17:00
    dinner_end = 22 * 60 + 15  # 22:15

    # Lunch: 11:15 AM - 2:00 PM (11:15 - 14:00)
    lunch_start = 11 * 60 + 15  # 11:15
    lunch_end = 14 * 60  # 14:00

    if dinner_start <= time_val <= dinner_end:
        return ("Dinner", RES_TYPE_ID["Dinner"])
    elif lunch_start <= time_val <= lunch_end:
        return ("Lunch", RES_TYPE_ID["Lunch"])
    else:
        return None

# ---- VIP Window Parsing ----
def parse_vip_windows(raw: str) -> list[dict]:
    """
    Parse VIP_WINDOWS config into structured list.
    Format: DATE,START_TIME,END_TIME,PARTY_SIZES...
    Example: 2025-01-15,18:00,20:00,2,4

    Returns list of:
    {
        'date': datetime.date,
        'start_time': (hour, minute),
        'end_time': (hour, minute),
        'party_sizes': [2, 4],
        'raw_line': '2025-01-15,18:00,20:00,2,4'
    }
    """
    if not raw:
        return []

    windows = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                print(f"⚠️  Skipping invalid VIP window (need date,start,end,party_sizes): {line}")
                continue

            date_str = parts[0]
            start_str = parts[1]
            end_str = parts[2]
            party_sizes = [int(p) for p in parts[3:]]

            # Parse date
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Parse times
            start_h, start_m = parse_hm(start_str)
            end_h, end_m = parse_hm(end_str)

            windows.append({
                'date': date_obj,
                'start_time': (start_h, start_m),
                'end_time': (end_h, end_m),
                'party_sizes': party_sizes,
                'raw_line': line
            })

        except Exception as e:
            print(f"⚠️  Error parsing VIP window '{line}': {e}")
            continue

    return windows

def is_window_active(window: dict, now_local: datetime) -> bool:
    """Check if VIP window is still active (hasn't expired yet)"""
    end_dt = datetime(
        window['date'].year,
        window['date'].month,
        window['date'].day,
        window['end_time'][0],
        window['end_time'][1],
        tzinfo=NYC
    )
    return now_local <= end_dt

def iter_vip_time_slots(window: dict, step_minutes: int):
    """
    Generate all time slots to check within a VIP window.
    Yields datetime objects in restaurant timezone.
    """
    start_h, start_m = window['start_time']
    end_h, end_m = window['end_time']

    current = datetime(
        window['date'].year,
        window['date'].month,
        window['date'].day,
        start_h,
        start_m,
        tzinfo=NYC
    )

    end = datetime(
        window['date'].year,
        window['date'].month,
        window['date'].day,
        end_h,
        end_m,
        tzinfo=NYC
    )

    while current <= end:
        yield current
        current += timedelta(minutes=step_minutes)

# ---- Gist State Management ----
def gist_headers():
    if not (GIST_ID and GIST_TOKEN):
        return None
    return {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "VIPWatcher/1.0",
    }

def load_vip_state():
    """Load VIP-specific state from Gist (tracks notifications sent)"""
    if not (GIST_ID and GIST_TOKEN):
        print("⚠️  No GIST_ID/GIST_TOKEN - no state tracking")
        return {}
    try:
        resp = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=gist_headers(), timeout=15)
        resp.raise_for_status()
        files = resp.json().get("files", {})
        content = files.get(STATE_FILENAME, {}).get("content", "{}")
        data = json.loads(content)

        # Prune entries older than 7 days
        cutoff = int(time.time()) - 7*24*3600
        pruned = {k: v for k, v in data.items() if v.get("last_notified", 0) >= cutoff}

        print(f"📥 Loaded {len(pruned)} VIP state entries from Gist")
        return pruned
    except Exception as e:
        print(f"❌ Error loading VIP Gist state: {e}")
        return {}

def save_vip_state(state: dict):
    """Save VIP state to Gist"""
    if not (GIST_ID and GIST_TOKEN):
        return
    try:
        payload = {
            "files": {
                STATE_FILENAME: {
                    "content": json.dumps(state, separators=(",",":"))
                }
            }
        }
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=gist_headers(), json=payload, timeout=15)
        print(f"💾 Saved {len(state)} VIP state entries to Gist")
    except Exception as e:
        print(f"❌ Error saving VIP state: {e}")

# ---- Notifications ----
def notify(items: list[dict]):
    """Send notifications via Pushover and/or Slack"""
    if not items:
        return

    for it in items:
        text = it["message"]
        title = it.get("title", NOTIFICATION_PREFIX)
        url = it.get("url")
        url_title = it.get("url_title", PUSHOVER_URL_TITLE_DEFAULT)

        # Pushover
        if PUSHOVER_USER and PUSHOVER_TOKEN:
            data = {
                "token": PUSHOVER_TOKEN,
                "user": PUSHOVER_USER,
                "title": title,
                "message": text,
                "priority": PUSHOVER_PRIORITY,
                "sound": PUSHOVER_SOUND,
            }
            if url:
                data["url"] = url
                data["url_title"] = url_title
            try:
                resp = requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
                resp.raise_for_status()
                print(f"✅ Pushover notification sent")
            except Exception as e:
                print(f"❌ Pushover failed: {e}")

        # Slack webhook
        if SLACK_WEBHOOK:
            try:
                slack_text = f"*{title}*\n{text}"
                if url:
                    slack_text += f"\n<{url}|{url_title}>"
                resp = requests.post(SLACK_WEBHOOK, json={"text": slack_text}, timeout=10)
                resp.raise_for_status()
                print(f"✅ Slack notification sent")
            except Exception as e:
                print(f"❌ Slack failed: {e}")

        # Console log
        print(f"📣 {title} — {text}")

def send_test_notification():
    """Send a test notification to verify Pushover/Slack are working"""
    print("🧪 TEST NOTIFICATION ENABLED - Sending test alert...")

    test_item = {
        "title": "🧪 VIP Watcher Test",
        "message": "If you see this, VIP notifications are working correctly! ✅",
        "url": "https://github.com",
        "url_title": "GitHub Actions"
    }

    try:
        notify([test_item])
        print("✅ Test notification sent successfully!")
        return True
    except Exception as e:
        print(f"❌ Test notification failed: {e}")
        return False

# ---- Safety Tracking ----
class RateLimiter:
    def __init__(self, max_per_hour: int):
        self.max_per_hour = max_per_hour
        self.calls = []

    def can_call(self) -> bool:
        now = time.time()
        # Remove calls older than 1 hour
        self.calls = [t for t in self.calls if now - t < 3600]
        return len(self.calls) < self.max_per_hour

    def record_call(self):
        self.calls.append(time.time())

    def remaining(self) -> int:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < 3600]
        return max(0, self.max_per_hour - len(self.calls))

# ---- Run Tracking (Supabase) ----
def create_run_record():
    """Create a watcher_runs row at the start of each VIP run."""
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    github_run_url = f"{GITHUB_SERVER}/{GITHUB_REPO}/actions/runs/{GITHUB_RUN_ID}" if GITHUB_RUN_ID else None
    config_snapshot = {
        "vip_windows": VIP_WINDOWS_RAW,
        "step_min": STEP_MIN,
        "max_checks_per_hour": MAX_CHECKS_PER_HOUR,
        "randomize_delay": RANDOMIZE_DELAY,
    }
    payload = {
        "run_type": "vip",
        "merchant_id": MERCHANT_ID,
        "restaurant_name": RESTAURANT_NAME,
        "status": "running",
        "config": json.dumps(config_snapshot),
        "github_run_id": GITHUB_RUN_ID or None,
        "github_run_url": github_run_url,
    }
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/watcher_runs",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        rows = resp.json()
        run_id = rows[0]["id"] if rows else None
        print(f"📋 VIP Run record created: {run_id}")
        return run_id
    except Exception as e:
        print(f"⚠️  Failed to create VIP run record: {e}")
        return None

def log_run_event(run_id, slot_key, slot_at_iso, service, party_size, lead_days, action, reason, suppression_type=None):
    """Log a single slot decision to the run_events table."""
    if not run_id or not (SUPABASE_URL and SUPABASE_KEY):
        return
    payload = {
        "run_id": run_id,
        "slot_key": slot_key,
        "slot_at_iso": slot_at_iso,
        "service": service,
        "party_size": party_size,
        "lead_days": lead_days,
        "action": action,
        "reason": reason,
        "suppression_type": suppression_type,
    }
    try:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/run_events",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            json=payload,
            timeout=10
        )
    except Exception:
        pass

def complete_run_record(run_id, status="success", slots_checked=0, slots_found=0, notifications_sent=0, slots_suppressed=0, api_calls_made=0, api_calls_failed=0, error_message=None):
    """Update the watcher_runs row with final counts."""
    if not run_id or not (SUPABASE_URL and SUPABASE_KEY):
        return
    payload = {
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "slots_checked": slots_checked,
        "slots_found": slots_found,
        "notifications_sent": notifications_sent,
        "slots_suppressed": slots_suppressed,
        "api_calls_made": api_calls_made,
        "api_calls_failed": api_calls_failed,
    }
    if error_message:
        payload["error_message"] = error_message
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/watcher_runs?id=eq.{run_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            json=payload,
            timeout=10
        )
    except Exception as e:
        print(f"⚠️  Failed to complete VIP run record: {e}")

# ---- Main Logic ----
def run_vip_watcher():
    print("="*60)
    print("🔥💎 VIP WATCHER STARTING 💎🔥")
    print("="*60)
    print(f"Restaurant: {RESTAURANT_NAME}")
    print(f"Merchant ID: {MERCHANT_ID}")
    print(f"Timezone: {TIMEZONE}")
    print("")

    # Send test notification if enabled
    if TEST_NOTIFICATION:
        send_test_notification()
        print("")

    # Optional: random delay at start (0-30s) to avoid detection patterns
    if RANDOMIZE_DELAY:
        delay = random.uniform(0, 30)
        print(f"⏱️  Random startup delay: {delay:.1f}s")
        time.sleep(delay)

    # Parse VIP windows
    windows = parse_vip_windows(VIP_WINDOWS_RAW)
    if not windows:
        print("ℹ️  No VIP windows configured. Add date/time windows to VIP_WINDOWS in workflow.")
        print("   Format: YYYY-MM-DD,HH:MM,HH:MM,party_sizes")
        print("   Example: 2025-01-15,18:00,20:00,2,4")
        return

    print(f"📋 Found {len(windows)} configured VIP window(s):")
    for w in windows:
        print(f"   • {w['date']} {w['start_time'][0]:02d}:{w['start_time'][1]:02d}-{w['end_time'][0]:02d}:{w['end_time'][1]:02d} (party: {w['party_sizes']})")
    print("")

    # Filter to active windows only
    now_local = datetime.now(NYC)
    active_windows = [w for w in windows if is_window_active(w, now_local)]

    if not active_windows:
        print("ℹ️  All VIP windows have expired. Nothing to check.")
        return

    print(f"✅ {len(active_windows)} active VIP window(s) to monitor")
    print("")

    # Load state
    state = load_vip_state()

    # Rate limiter
    limiter = RateLimiter(MAX_CHECKS_PER_HOUR)

    # Track findings and stats
    notifications = []
    api_calls_made = 0
    api_calls_failed = 0
    total_slots_checked = 0
    suppressed_count = 0
    found_this_run = set()  # prevent duplicate notifications in same run
    window_stats = {}  # track slots per window
    service_stats = {}  # track slots per service type (Lunch/Dinner)
    start_time = time.time()

    # --- Run tracking ---
    run_id = create_run_record()

    # Check each active window
    for window in active_windows:
        window_key = f"{window['date']}"
        window_stats[window_key] = 0

        print(f"🔍 Checking VIP window: {window['date']} {window['start_time'][0]:02d}:{window['start_time'][1]:02d}-{window['end_time'][0]:02d}:{window['end_time'][1]:02d}")

        # Generate time slots to probe
        for slot_dt in iter_vip_time_slots(window, STEP_MIN):
            # Determine service type (Lunch/Dinner)
            service_info = determine_service_type(slot_dt)
            if not service_info:
                continue

            service_name, type_id = service_info

            # Check each party size
            for party in window['party_sizes']:
                # Rate limit check
                if not limiter.can_call():
                    print(f"⚠️  Rate limit reached ({MAX_CHECKS_PER_HOUR}/hour). Stopping checks.")
                    break

                total_slots_checked += 1
                window_stats[window_key] += 1
                service_stats[service_name] = service_stats.get(service_name, 0) + 1

                # Random stagger between API calls
                if RANDOM_STAGGER:
                    delay_ms = random.randint(*RANDOM_STAGGER)
                    time.sleep(delay_ms / 1000.0)

                # Probe API with detailed logging
                slot_time_str = slot_dt.strftime('%Y-%m-%d %H:%M')
                print(f"  ⏰ Probing: {slot_time_str}, party {party}, {service_name}", end=" ")

                try:
                    ts_ms = to_epoch_ms(slot_dt)
                    data = probe(ts_ms, party, type_id)
                    api_calls_made += 1
                    limiter.record_call()

                    # Count how many slots returned
                    slots_returned = 0
                    for block in data.get("types", []):
                        if block.get("reservation_type_id") == type_id:
                            slots_returned += len(block.get("times", []))

                    print(f"→ ✅ API success ({slots_returned} slot{'s' if slots_returned != 1 else ''})")

                except Exception as e:
                    api_calls_failed += 1
                    print(f"→ ❌ API failed: {e}")
                    continue

                # Parse results
                for block in data.get("types", []):
                    if block.get("reservation_type_id") != type_id:
                        continue

                    for slot in block.get("times", []):
                        iso = slot.get("time")
                        label = slot.get("label") or slot.get("display_time")
                        url = slot.get("booking_url") or slot.get("reserve_url")

                        date_str, time_str = format_when(iso, label, slot_dt)

                        # Create unique key
                        key = f"VIP|{MERCHANT_ID}|{date_str}|{time_str}|{party}|{service_name}"

                        # Skip if already notified in this run
                        if key in found_this_run:
                            continue

                        print(f"🎯 VIP SLOT FOUND: {date_str} @ {time_str} for party {party} ({service_name})")

                        slot_iso_str = slot_dt.isoformat(timespec="seconds")
                        lead_days = max((slot_dt.date() - datetime.now(NYC).date()).days, 0)

                        # Check if we've notified about this recently (within 5 minutes)
                        now_ts = int(time.time())
                        last_notified = state.get(key, {}).get("last_notified", 0)

                        # For VIP, we use very short cooldown (5 min) to avoid spam but ensure urgency
                        min_gap = 5 * 60

                        if (now_ts - last_notified) < min_gap:
                            print(f"   ⏭️  Recently notified ({int((now_ts-last_notified)/60)} min ago), skipping")
                            suppressed_count += 1
                            log_run_event(run_id, key, slot_iso_str, service_name, party, lead_days, "SUPPRESSED", f"COOLDOWN_{int((now_ts-last_notified)/60)}min", "cooldown")
                            continue

                        # Mark as notified
                        state[key] = {"last_notified": now_ts}
                        found_this_run.add(key)
                        log_run_event(run_id, key, slot_iso_str, service_name, party, lead_days, "NOTIFIED", "VIP_ALERT")

                        # Build notification
                        candidate_url = f"{LINK_BASE}?reservation_type_id={type_id}&party_size={party}&search_ts={ts_ms}"
                        final_url = url or candidate_url

                        notifications.append({
                            "title": NOTIFICATION_PREFIX,
                            "message": f"{date_str} @ {time_str}, party of {party}. BOOK NOW!",
                            "url": final_url,
                            "url_title": PUSHOVER_URL_TITLE_DEFAULT
                        })

    # Summary
    elapsed_time = time.time() - start_time

    print("")
    print("="*60)
    print("📊 VIP WATCHER SUMMARY")
    print("="*60)
    print(f"Active VIP windows: {len(active_windows)}")
    print(f"Time slots checked: {total_slots_checked}")
    print("")

    # Window breakdown
    if window_stats:
        print("Window Breakdown:")
        for date_str in sorted(window_stats.keys()):
            count = window_stats[date_str]
            print(f"  • {date_str}: {count} slot{'s' if count != 1 else ''} checked")
        print("")

    # Service type breakdown
    if service_stats:
        print("Service Type Breakdown:")
        for service, count in sorted(service_stats.items()):
            print(f"  • {service}: {count} slot{'s' if count != 1 else ''}")
        print("")

    # API stats
    api_success_rate = (api_calls_made / (api_calls_made + api_calls_failed) * 100) if (api_calls_made + api_calls_failed) > 0 else 0
    print("API Stats:")
    print(f"  • Calls made: {api_calls_made}")
    print(f"  • Success: {api_calls_made}/{api_calls_made + api_calls_failed} ({api_success_rate:.1f}%)")
    if api_calls_failed > 0:
        print(f"  • Failed: {api_calls_failed}")
    print(f"  • Rate limit remaining: {limiter.remaining()}/{MAX_CHECKS_PER_HOUR} per hour")
    print(f"  • Time elapsed: {elapsed_time:.1f}s")
    print("")

    # Results
    print(f"Slots found: {len(found_this_run)}")
    print(f"Notifications sent: {len(notifications)}")
    print(f"Slots suppressed: {suppressed_count}")

    if found_this_run:
        print("\n🎯 VIP Slots Found:")
        for key in sorted(found_this_run):
            parts = key.split("|")
            if len(parts) >= 5:
                print(f"   • {parts[2]} @ {parts[3]} for party {parts[4]}")

    print("="*60 + "\n")

    # Save state and send notifications
    if state:
        save_vip_state(state)

    if notifications:
        notify(notifications)
    else:
        print("ℹ️  No new VIP slots found this run")

    # --- Complete run tracking ---
    complete_run_record(
        run_id,
        status="success",
        slots_checked=total_slots_checked,
        slots_found=len(found_this_run),
        notifications_sent=len(notifications),
        slots_suppressed=suppressed_count,
        api_calls_made=api_calls_made,
        api_calls_failed=api_calls_failed,
    )

if __name__ == "__main__":
    run_vip_watcher()
