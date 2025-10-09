# watcher.py
import os, time, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ---- Config via ENV (set in GitHub Secrets) ----
MERCHANT_ID   = os.getenv("MERCHANT_ID", "278278")
PARTY_SIZES   = [int(x) for x in os.getenv("PARTY_SIZES", "2,4").split(",")]
ENABLE_DINNER = os.getenv("ENABLE_DINNER", "true").lower() == "true"
ENABLE_LUNCH  = os.getenv("ENABLE_LUNCH", "false").lower() == "true"
DAYS_AHEAD    = int(os.getenv("DAYS_AHEAD", "3"))      # last-minute focus
STEP_MIN      = int(os.getenv("STEP_MIN", "15"))       # 15-min grid
LINK_BASE     = os.getenv("LINK_BASE", "https://example.com")

# Notifications (choose one or both)
PUSHOVER_USER = os.getenv("PUSHOVER_USER")  # optional
PUSHOVER_TOKEN= os.getenv("PUSHOVER_TOKEN") # optional
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")  # optional

# ---- Constants ----
NYC = ZoneInfo("America/New_York")
BASE_URL = "https://loyaltyapi.wisely.io/v2/web/reservations/inventory"
RES_TYPE_ID = {"Dinner": 1695, "Lunch": 1862}
DINNER_WINDOW = ("17:00", "22:15")
LUNCH_WINDOW  = ("11:15", "14:30")

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
        headers={"Accept":"application/json","User-Agent":"HillstoneWatch/1.0"},
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

def notify(lines: list[str]):
    if not lines: return
    text = "\n".join(lines)

    # Pushover (if configured)
    if PUSHOVER_USER and PUSHOVER_TOKEN:
        try:
            requests.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
                      "title": "Hillstone Park Ave", "message": text},
                timeout=10,
            )
        except Exception:
            pass

    # Slack webhook (if configured)
    if SLACK_WEBHOOK:
        try:
            requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        except Exception:
            pass

    # Always print to logs too
    print(text)

def run_once():
    svcs = enabled_services()
    today = datetime.now(tz=NYC).date()
    found_keys, lines = set(), []

    for i in range(DAYS_AHEAD):
        d = today + timedelta(days=i)
        for svc_name, type_id, (start_hm, end_hm) in svcs:
            for dt in iter_grid(d, start_hm, end_hm, STEP_MIN):
                ts = to_epoch_ms(dt)
                for party in PARTY_SIZES:
                    try:
                        data = probe(ts, party, type_id)
                    except Exception:
                        continue
                    for block in data.get("types", []):
                        if block.get("reservation_type_id") != type_id: continue
                        for slot in block.get("times", []):
                            iso  = slot.get("time")
                            label= slot.get("label") or slot.get("display_time")
                            url  = slot.get("booking_url") or slot.get("reserve_url") or LINK_BASE

                            date_str, time_str = format_when(iso, label, dt)
                            key = (date_str, time_str, party, svc_name)
                            if key in found_keys: continue
                            found_keys.add(key)

                            # Candidate deep link with context (works if the site honors params)
                            candidate = f"{LINK_BASE}?reservation_type_id={type_id}&party_size={party}&search_ts={ts}"
                            link = url or candidate

                            lines.append(
                                f"Woohoo! New table for {party} on {date_str} @ {time_str} ({svc_name}). "
                                f"Act fast! {link}"
                            )
                time.sleep(0.05)  # be polite

    if not lines:
        print("No openings this run.")
    else:
        notify(lines)

if __name__ == "__main__":
    run_once()
