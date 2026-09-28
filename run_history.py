"""Small, bounded run snapshots published with the GitHub Pages dashboard."""

import atexit
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_RUNS = 200
MAX_EVENTS = 50
_active = {}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save(run):
    path = Path("dashboard") / f"{run['run_type']}-runs.json"
    history = json.loads(path.read_text()) if path.exists() else {"runs": []}
    runs = [run] + [row for row in history["runs"] if row["id"] != run["id"]]
    history = {"updated_at": now(), "runs": sorted(runs, key=lambda row: row["started_at"], reverse=True)[:MAX_RUNS]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, separators=(",", ":")) + "\n")
    temporary.replace(path)


def create(payload):
    run = {**payload, "id": str(uuid.uuid4()), "started_at": now(), "completed_at": None,
           "status": "running", "events": [], "total_events": 0,
           "slots_checked": 0, "slots_found": 0, "notifications_sent": 0, "slots_suppressed": 0}
    _active[run["id"]] = run
    save(run)
    return run["id"]


def event(run_id, **payload):
    run = _active.get(run_id)
    if run is None:
        return
    run["total_events"] += 1
    events = run["events"]
    item = {**payload, "created_at": now()}
    if len(events) < MAX_EVENTS:
        events.append(item)
    elif payload.get("action") == "NOTIFIED":
        # Match the status UI: prioritize notifications over skipped slots.
        for index in range(len(events) - 1, -1, -1):
            if events[index]["action"] != "NOTIFIED":
                events[index] = item
                break


def complete(run_id, **payload):
    run = _active.get(run_id)
    if run is None:
        return
    run.update(payload, completed_at=now())
    save(run)
    del _active[run_id]


@atexit.register
def record_interrupted_runs():
    for run_id in list(_active):
        complete(run_id, status="error", error_message="Watcher exited before completing; see GitHub Actions logs.")
