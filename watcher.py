import os
import requests
import json
import time
from datetime import datetime
from collections import defaultdict
from gist import load_gist, save_gist
from notify import pushover
from search import get_availability_for_venue


# -----------------------
# CONFIG / ENV VARS
# -----------------------
PARTY_SIZES = [int(x) for x in os.getenv("PARTY_SIZES", "2,4").split(",")]
RENOTIFY_MINUTES = int(os.getenv("RENOTIFY_MINUTES", "40"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
VENUES = json.loads(os.getenv("VENUES_JSON", '[{"id": "278278", "name": "Hillstone Park Ave"}]'))

PUSHOVER_USER = os.getenv("PUSHOVER_USER")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")

# -----------------------
# HELPERS
# -----------------------
def now_ts():
    return int(time.time())

def group_slots_by_time(results):
    """
    Build a dictionary:
      {
        '2025-10-14T19:30': set([2, 4])
      }
    """
    grouped = defaultdict(set)
    for r in results:
        if r.get("party_size") in PARTY_SIZES:
            slot_key = f"{r['date']}T{r['time']}"
            grouped[slot_key].add(r["party_size"])
    return grouped


def format_message(date_str, time_str, sizes):
    if sizes == {2}:
        size_part = "2"
    elif sizes == {4}:
        size_part = "4"
    elif sizes == {2, 4} or sizes == {4, 2}:
        size_part = "2 or 4"
    else:
        return None
    return f"{date_str} @ {time_str} for {size_part}. Act fast!"


# -----------------------
# MAIN WATCHER LOGIC
# -----------------------
def main():
    seen = load_gist()
    now = now_ts()

    for venue in VENUES:
        venue_id = venue["id"]
        venue_name = venue.get("name", venue_id)

        results = get_availability_for_venue(venue_id)
        current_slots = group_slots_by_time(results)
        present_this_run = set(current_slots.keys())

        for dt_key, sizes in current_slots.items():
            date_str, time_str = dt_key.split("T")
            entry = seen.get(dt_key, {})
            was_present = entry.get("present", False)
            last_alert_ts = entry.get("last_alert", 0)

            # Should we notify?
            should_notify = False
            reason = ""

            if not was_present:
                should_notify = True
                reason = "new or reappeared"
            elif now - last_alert_ts >= RENOTIFY_MINUTES * 60:
                should_notify = True
                reason = f"renotify cooldown passed ({RENOTIFY_MINUTES} min)"

            if should_notify:
                msg = format_message(date_str, time_str, sizes)
                if msg:
                    pushover(msg, PUSHOVER_USER, PUSHOVER_TOKEN)
                    print(f"[NOTIFIED] {msg} ({reason})")
                    # Update seen
                    seen[dt_key] = {
                        "present": True,
                        "last_seen": now,
                        "last_alert": now,
                        "sizes": sorted(list(sizes)),
                    }
                else:
                    print(f"[SKIPPED] {dt_key} — unhandled party size combo: {sizes}")
            else:
                # Still present, no need to alert
                seen[dt_key]["present"] = True
                seen[dt_key]["last_seen"] = now

        # Mark any previously-present slots that were NOT seen this run as absent
        for k, r in seen.items():
            if k not in present_this_run and r.get("present"):
                r["present"] = False
                print(f"[MARKED ABSENT] {k}")

    save_gist(seen)


if __name__ == "__main__":
    main()
