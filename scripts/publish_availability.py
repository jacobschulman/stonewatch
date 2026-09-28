"""Merge the current run into monthly unique-slot CSVs and publish their index."""

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FIELDS = ["seen_at_iso", "slot_at_iso", "lead_minutes", "lead_hours", "service",
          "party_size", "weekday_slot", "weekday_seen", "hour_slot", "merchant_id", "source"]
NYC = ZoneInfo("America/New_York")


def read_rows(path):
    with Path(path).open(newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"Unexpected availability columns: {path}")
        rows = list(reader)
    for row in rows:
        if None in row or None in row.values():
            raise ValueError(f"Invalid availability row in {path}")
        for field in ("slot_at_iso", "seen_at_iso"):
            if datetime.fromisoformat(row[field]).tzinfo is None:
                raise ValueError(f"Missing timezone in {path}")
        if int(row["party_size"]) <= 0 or not row["service"]:
            raise ValueError(f"Invalid slot in {path}")
    return rows


def slot_key(row):
    return (datetime.fromisoformat(row["slot_at_iso"]), int(row["party_size"]),
            row["service"], row["merchant_id"])


def merge_rows(rows):
    slots = {}
    for row in rows:
        key = slot_key(row)
        if key not in slots or datetime.fromisoformat(row["seen_at_iso"]) < datetime.fromisoformat(slots[key]["seen_at_iso"]):
            slots[key] = row
    return sorted(slots.values(), key=slot_key)


def atomic_write(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def publish(input_path="availability_log.csv", output_dir="data/availability"):
    input_path, output_dir = Path(input_path), Path(output_dir)
    manifest_path = output_dir / "index.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"version": 1, "months": []}
    if manifest["version"] != 1:
        raise ValueError("Unsupported availability index version")
    entries = {entry["month"]: entry for entry in manifest["months"]}
    incoming = read_rows(input_path) if input_path.exists() else []
    batches = defaultdict(list)
    for row in incoming:
        # A stable reservation month keeps all sightings of a slot in one shard,
        # including sightings on opposite sides of a month or UTC boundary.
        month = datetime.fromisoformat(row["slot_at_iso"]).astimezone(NYC).strftime("%Y-%m")
        batches[month].append(row)

    updates = []
    for month, rows in sorted(batches.items()):
        path = output_dir / f"{month}.csv"
        merged = merge_rows((read_rows(path) if path.exists() else []) + rows)
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(merged)
        content = buffer.getvalue()
        digest = hashlib.sha256(content.encode()).hexdigest()
        if entries.get(month, {}).get("sha256") == digest:
            continue
        seen = [datetime.fromisoformat(row["seen_at_iso"]).astimezone(timezone.utc) for row in merged]
        entries[month] = {"month": month, "file": path.name, "rows": len(merged),
                          "bytes": len(content.encode()), "sha256": digest,
                          "first_seen": min(seen).isoformat(), "last_seen": max(seen).isoformat()}
        updates.append((path, content))

    output_dir.mkdir(parents=True, exist_ok=True)
    for path, content in updates:
        atomic_write(path, content)
    if updates or not manifest_path.exists():
        manifest = {"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
                    "total_slots": sum(entry["rows"] for entry in entries.values()),
                    "months": [entries[month] for month in sorted(entries)]}
        atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
    # Keep the buffer transient and bounded. Only the monthly files are committed.
    if input_path.exists():
        input_path.unlink()
    return len(incoming), len(updates), manifest["total_slots"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="availability_log.csv")
    parser.add_argument("--output-dir", default="data/availability")
    args = parser.parse_args()
    incoming, changed, total = publish(args.input, args.output_dir)
    print(f"Published {incoming:,} sightings into {changed} changed monthly files; {total:,} unique slots total")
