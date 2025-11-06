# watcher.py
import os, time, json, requests, csv
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---- Config via ENV ----
MERCHANT_ID   = os.getenv("MERCHANT_ID", "278278")
RESTAURANT_NAME  = os.getenv("RESTAURANT_NAME", "Hillstone NYC")
TIMEZONE         = os.getenv("TIMEZONE", "America/New_York")
NOTIFICATION_PREFIX = os.getenv("NOTIFICATION_PREFIX", "🍸🚨 New Resy 🚨🍸")
PARTY_SIZES   = [int(x) for x in os.getenv("PARTY_SIZES", "2,4").split(",")]
ENABLE_DINNER = os.getenv("ENABLE_DINNER", "true").lower() == "true"
ENABLE_LUNCH  = os.getenv("ENABLE_LUNCH", "false").lower() == "true"
DAYS_AHEAD    = int(os.getenv("DAYS_AHEAD", "3"))
STEP_MIN      = int(os.getenv("STEP_MIN", "15"))
LINK_BASE     = os.getenv("LINK_BASE", "https://example.com")
RENOTIFY_MINUTES = int(os.getenv("RENOTIFY_MINUTES", "120"))  # 2 hours default
LUNCH_MAX_DAYS   = int(os.getenv("LUNCH_MAX_DAYS",   "2"))
DINNER_MAX_DAYS  = int(os.getenv("DINNER_MAX_DAYS",  "3"))
MILESTONES       = [int(x) for x in os.getenv("MILESTONES", "3,1,0").split(",") if x.strip()]
DAILY_CAP_LUNCH  = int(os.getenv("DAILY_CAP_LUNCH",  "1"))
DAILY_CAP_DINNER = int(os.getenv("DAILY_CAP_DINNER", "0"))

# Notifications
PUSHOVER_USER = os.getenv("PUSHOVER_USER")
PUSHOVER_TOKEN= os.getenv("PUSHOVER_TOKEN")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
PUSHOVER_TITLE  = os.getenv("PUSHOVER_TITLE", "🚨 New Table At Stone 🚨")  # default fun title
PUSHOVER_SOUND  = os.getenv("PUSHOVER_SOUND")  # e.g., "magic", "siren", "bike"
PUSHOVER_PRIORITY = os.getenv("PUSHOVER_PRIORITY", "0")  # -2..2, "0" normal
PUSHOVER_URL_TITLE_DEFAULT = os.getenv("PUSHOVER_URL_TITLE", "Book now")

# X/Twitter
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# Gist state (cross-run dedupe)
GIST_ID       = os.getenv("GIST_ID")      # required for cross-run dedupe
GIST_TOKEN    = os.getenv("GIST_TOKEN")   # required for cross-run dedupe
STATE_FILENAME = f"seen_{MERCHANT_ID}.json"
STATE_TTL_DAYS= 5  # keep keys for 5 days, then prune

# ---- Constants ----
NYC = ZoneInfo(TIMEZONE)
BASE_URL = "https://loyaltyapi.wisely.io/v2/web/reservations/inventory"
RES_TYPE_ID = {"Dinner": 1695, "Lunch": 1862}
DINNER_WINDOW = ("17:00", "22:15")
LUNCH_WINDOW  = ("11:15", "14:00")

def enabled_services():
    svcs = []
    if ENABLE_DINNER: svcs.append(("Dinner", RES_TYPE_ID["Dinner"], DINNER_WINDOW))
    if ENABLE_LUNCH:  svcs.append(("Lunch",  RES_TYPE_ID["Lunch"],  LUNCH_WINDOW))
    if not svcs:
        raise SystemExit("No services enabled. Set ENABLE_DINNER or ENABLE_LUNCH to true.")
    return svcs

def to_epoch_ms(dt_local: datetime) -> int:
    return int(dt_local.timestamp() * 1000)

def parse_hm(hm: str):
    h, m = map(int, hm.split(":")); return h, m

def iter_grid(day, start_hm, end_hm, step_min):
    sh, sm = parse_hm(start_hm); eh, em = parse_hm(end_hm)
    t = datetime(day.year, day.month, day.day, sh, sm, tzinfo=NYC)
    end = datetime(day.year, day.month, day.day, eh, em, tzinfo=NYC)
    while t <= end:
        yield t
        t += timedelta(minutes=step_min)

def probe(ts_ms: int, party: int, type_id: int) -> dict:
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

# ---------- Cross-run state via Gist ----------
def gist_headers():
    if not (GIST_ID and GIST_TOKEN):
        return None
    return {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ResyWatchState/1.0",
    }

def load_seen():
    if not (GIST_ID and GIST_TOKEN):
        print("⚠️  No GIST_ID or GIST_TOKEN - skipping load")
        return {}
    try:
        print(f"📥 Attempting to load from Gist {GIST_ID}")
        resp = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=gist_headers(), timeout=15)
        resp.raise_for_status()
        files = resp.json().get("files", {})
        print(f"📁 Files in Gist: {list(files.keys())}")
        content = files.get(STATE_FILENAME, {}).get("content", "{}")
        print(f"📄 Content length: {len(content)} chars")
        data = json.loads(content)
        print(f"📊 Parsed {len(data)} entries from Gist")
        
        # prune old entries
        cutoff = int(time.time()) - STATE_TTL_DAYS*24*3600
        pruned = {}
        for k, v in data.items():
            timestamp = v if isinstance(v, int) else v.get("last_notified", 0) if isinstance(v, dict) else 0
            if timestamp >= cutoff:
                pruned[k] = v
        print(f"✅ After pruning: {len(pruned)} entries remain")
        return pruned
    except Exception as e:
        print(f"❌ Error loading Gist: {e}")
        return {}

def save_seen(seen: dict):
    if not (GIST_ID and GIST_TOKEN):
        return
    try:
        payload = {
            "files": {
                STATE_FILENAME: {
                    "content": json.dumps(seen, separators=(",",":"))
                }
            }
        }
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=gist_headers(), json=payload, timeout=15)
    except Exception:
        pass

# ----------- Notifiers -----------
def notify(items: list[dict]):
    """
    items: list of dicts with keys:
      - title (str)
      - message (str)
      - url (str, optional)
      - url_title (str, optional)
    """
    if not items:
        return

    for it in items:
        text  = it["message"]
        title = it.get("title", PUSHOVER_TITLE)
        url   = it.get("url")
        url_title = it.get("url_title", PUSHOVER_URL_TITLE_DEFAULT)

        # Pushover
        if PUSHOVER_USER and PUSHOVER_TOKEN:
            data = {
                "token": PUSHOVER_TOKEN,
                "user": PUSHOVER_USER,
                "title": title,
                "message": text,
                "priority": PUSHOVER_PRIORITY,
            }
            if PUSHOVER_SOUND:
                data["sound"] = PUSHOVER_SOUND
            if url:
                data["url"] = url
                data["url_title"] = url_title
            try:
                requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=10)
            except Exception:
                pass

        # Slack webhook (optional)
        if SLACK_WEBHOOK:
            try:
                slack_text = f"*{title}*\n{text}"
                if url:
                    slack_text += f"\n<{url}|{url_title}>"
                requests.post(SLACK_WEBHOOK, json={"text": slack_text}, timeout=10)
            except Exception:
                pass

        # X/Twitter
        if all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET]):
            try:
                import tweepy
                client = tweepy.Client(
                    consumer_key=TWITTER_API_KEY,
                    consumer_secret=TWITTER_API_SECRET,
                    access_token=TWITTER_ACCESS_TOKEN,
                    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
                )

                # Build tweet (max 280 chars)
                tweet = f"{title}\n{text}"
                if url:
                    tweet += f"\n{url}"

                # Truncate if too long
                if len(tweet) > 280:
                    tweet = tweet[:277] + "..."

                client.create_tweet(text=tweet)
                print(f"🐦 Posted to X: {tweet}")
            except Exception as e:
                print(f"❌ X post failed: {e}")

        # Always echo to logs
        print(f"{title} — {text}")

# ---------- Logging setup ----------
LOG_FILE = f"availability_log_{MERCHANT_ID}.csv"
CSV_HEADER = [
    "seen_at_iso", "slot_at_iso",
    "lead_minutes", "lead_hours",
    "service", "party_size",
    "weekday_slot", "weekday_seen", "hour_slot",
    "merchant_id", "source"
]

def ensure_csv_header(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADER)

def log_slot_event(slot_dt_nyc, seen_dt_utc, service, party_size, merchant_id="278278", source="wisely"):
    ensure_csv_header(LOG_FILE)
    lead = (slot_dt_nyc.astimezone(timezone.utc) - seen_dt_utc).total_seconds() / 60.0
    lead_hours = round(lead / 60.0, 1)
    row = [
        seen_dt_utc.isoformat(timespec="seconds"),
        slot_dt_nyc.isoformat(timespec="seconds"),
        int(round(lead)), lead_hours,
        service, int(party_size),
        slot_dt_nyc.strftime("%a"),
        seen_dt_utc.astimezone(NYC).strftime("%a"),
        int(slot_dt_nyc.strftime("%H")),
        merchant_id, source
    ]
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow(row)

def compute_slot_dt_nyc(iso, label, probed_dt_nyc):
    # Prefer ISO if present; else combine label time with the probed date
    if iso:
        try:
            return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(NYC)
        except Exception:
            pass
    if label:
        try:
            t_only = datetime.strptime(label.strip().upper(), "%I:%M %p")
            return probed_dt_nyc.replace(hour=t_only.hour, minute=t_only.minute, second=0, microsecond=0)
        except Exception:
            return probed_dt_nyc
    return probed_dt_nyc

def nyc_today_str():
    return datetime.now(NYC).strftime("%Y-%m-%d")

def lead_days_int(slot_dt_nyc):
    """Whole days between now (NYC) and the slot. Floor at 0 for past/same-day quirks."""
    delta = (slot_dt_nyc.date() - datetime.now(NYC).date()).days
    return max(delta, 0)

def current_milestone(lead_days: int) -> int | None:
    """
    Given a list like [3,1,0], return the highest milestone reached for the current lead_days.
    Example: lead_days=2 -> 3; lead_days=1 -> 1; lead_days=0 -> 0; lead_days=5 -> None
    """
    reached = [m for m in MILESTONES if lead_days <= m]
    return max(reached) if reached else None

def daily_cap_for(service_name: str) -> int:
    return DAILY_CAP_LUNCH if service_name.lower().startswith("lunch") else DAILY_CAP_DINNER

def max_days_for(service_name: str) -> int:
    return LUNCH_MAX_DAYS if service_name.lower().startswith("lunch") else DINNER_MAX_DAYS

# RUN ONCE NOTIFICATION SETTINGS

def run_once():
    svcs = enabled_services()
    today = datetime.now(tz=NYC).date()
    seen = load_seen()
    now_ts = int(time.time())
    items = []
    grouped_slots = {}  # key: (date_str, time_str, svc_name), value: list of (party, link)
    found_this_run = set()
    present_this_run = set()

    for i in range(DAYS_AHEAD):
        d = today + timedelta(days=i)
        for svc_name, type_id, (start_hm, end_hm) in svcs:
            for dt in iter_grid(d, start_hm, end_hm, STEP_MIN):
                ts = to_epoch_ms(dt)
                for party in PARTY_SIZES:
                    try:
                        data = probe(ts, party, type_id)
                    except Exception as e:
                        print(f"❌ Probe failed: {e}")
                        continue
                    for block in data.get("types", []):
                        if block.get("reservation_type_id") != type_id: 
                            continue
                        for slot in block.get("times", []):
                            iso  = slot.get("time")
                            label= slot.get("label") or slot.get("display_time")
                            url  = slot.get("booking_url") or slot.get("reserve_url") or LINK_BASE

                            date_str, time_str = format_when(iso, label, dt)
                            print(f"🔍 Found slot: {svc_name} {date_str} @ {time_str} for party {party}")
                            key = f"{MERCHANT_ID}|{date_str}|{time_str}|{party}|{svc_name}"
                            # Skip if already seen this slot in this run
                            if key in found_this_run:
                                continue

                            # Compute slot datetime + lead days (NYC-local)
                            slot_dt_nyc = compute_slot_dt_nyc(iso, label, dt)
                            lead_days = lead_days_int(slot_dt_nyc)
                            # Absolute far-future suppression by meal (even first sighting)
                            if svc_name.lower().startswith("lunch") and lead_days > LUNCH_MAX_DAYS:
                                continue
                            if svc_name.lower().startswith("dinner") and lead_days > DINNER_MAX_DAYS:
                                continue

                            # --- Log every slot found (for data collection) ---
                            seen_dt_utc = datetime.now(timezone.utc)
                            log_slot_event(slot_dt_nyc, seen_dt_utc, svc_name, party, MERCHANT_ID, "wisely")


                            # Pull prior record from Gist, backward-compatible with old int format
                            rec = seen.get(key, {})
                            if isinstance(rec, int):
                                rec = {"last_notified": int(rec)}


                            # presence bookkeeping (used for reappear detection)
                            was_present = bool(rec.get("present", False))  # present in previous run?
                            rec["present"] = True                          # mark present now
                            present_this_run.add(key)

                            last_notified      = int(rec.get("last_notified", 0))
                            last_milestone     = rec.get("last_milestone")
                            last_notified_date = rec.get("last_notified_date")  # "YYYY-MM-DD" (NYC calendar day string)

                            # Meal-aware limits / caps
                            max_days    = max_days_for(svc_name)           # e.g., lunch 2, dinner 3 by default
                            daily_cap   = daily_cap_for(svc_name)          # e.g., lunch 1/day, dinner 0 (= no cap)
                            today_str   = nyc_today_str()
                            milestone   = current_milestone(lead_days)     # e.g., from [3,1,0], returns 3/1/0/None

                            min_gap = RENOTIFY_MINUTES * 60

                            # Decide if we should notify (presence-aware)
                            reappear = (last_notified > 0 and not was_present)  # was absent last run, now present

                            should_notify = False
                            notify_reason = None
                            
                            if last_notified == 0:
                                # First sighting: always notify (far-future already short-circuited above)
                                should_notify = True
                                notify_reason = "FIRST_SIGHTING"
                            elif reappear:
                                # Disappeared then reappeared = new cancellation → notify even same-day
                                should_notify = True
                                notify_reason = "REAPPEARED"
                            else:
                                # Daily cap (only if a cap > 0)
                                if daily_cap > 0 and last_notified_date == today_str:
                                    print(f"⏭️  SKIP (daily cap): {date_str} @ {time_str} for {party} - already notified today")
                                    continue
                                    
                                # Guard: inside meal window only
                                if lead_days > max_days:
                                    print(f"⏭️  SKIP (too far): {date_str} @ {time_str} for {party} - {lead_days} days away")
                                    continue
                            
                                # Milestones or cooldown
                                if milestone is not None and milestone != last_milestone:
                                    should_notify = True
                                    notify_reason = f"MILESTONE_{milestone}"
                                elif (now_ts - last_notified) >= min_gap:
                                    should_notify = True
                                    notify_reason = f"COOLDOWN_{int((now_ts - last_notified)/60)}min"
                            
                            if should_notify:
                                print(f"✅ NOTIFY ({notify_reason}): {date_str} @ {time_str} for {party}, lead={lead_days}d, last={int((now_ts-last_notified)/60)}min ago")
                            else:
                                continue
                            
                            # Mark as notified now (persist richer record)
                            rec["last_notified"] = now_ts
                            rec["last_milestone"] = milestone
                            rec["last_notified_date"] = today_str
                            seen[key] = rec
                            found_this_run.add(key)

                            
                            candidate = f"{LINK_BASE}?reservation_type_id={type_id}&party_size={party}&search_ts={ts}"
                            link = url or candidate

                            # --- Group by time slot for combined notifications ---
                            slot_key = (date_str, time_str, svc_name)
                            if slot_key not in grouped_slots:
                                grouped_slots[slot_key] = []
                            grouped_slots[slot_key].append((party, link))
                            
                time.sleep(0.05)

    # Build combined notifications from grouped slots
    for (date_str, time_str, svc_name), parties_info in grouped_slots.items():
        parties = sorted([p for p, _ in parties_info])
        party_str = " or ".join(str(p) for p in parties)
        
        # Use the first link
        link = parties_info[0][1]
        
        fun_title = NOTIFICATION_PREFIX
        msg = f"{date_str} @ {time_str}, for {party_str}. Act fast!"
        
        items.append({
            "title": fun_title,
            "message": msg,
            "url": link,
            "url_title": "Reserve Now"
        })
    
    # Mark any previously-present slots that were NOT seen this run as absent
    for k, r in list(seen.items()):
        if isinstance(r, int):
            continue  # upgrade to dict next time we see it
        if r.get("present", False) and k not in present_this_run:
            r["present"] = False

    # --- Summary Statistics ---
    print("\n" + "="*60)
    print("📊 RUN SUMMARY")
    print("="*60)
    print(f"Total slots checked: {len(present_this_run)}")
    print(f"New slots found this run: {len(found_this_run)}")
    print(f"Notifications sent: {len(items)}")
    
    if found_this_run:
        print(f"\n📍 Slots found:")
        for key in sorted(found_this_run):
            parts = key.split("|")
            print(f"  - {parts[1]} @ {parts[2]} for {parts[3]} ({parts[4]})")
    
    if items:
        print(f"\n✉️  Notifications sent:")
        for item in items:
            print(f"  - {item['message']}")
    
    print("="*60 + "\n")

    # Save updated state & notify
    save_seen(seen)
    
    # Save updated state & notify
    save_seen(seen)
    if items:
        notify(items)
    else:
        print("No NEW openings this run.")

if __name__ == "__main__":
    run_once()
