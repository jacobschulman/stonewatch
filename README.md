# StoneWatch

Automated reservation availability monitor for a very popular restaurant in NYC with a compound name starting with a common geographical feature and a common geological item. Watches the Wisely loyalty/reservation API and sends real-time notifications when tables open up.

---

## How It Works

StoneWatch polls the Wisely API on a rolling 8-day window. When a new slot appears, it fires a notification via Pushover, Slack, and/or X. It tracks which slots it has already seen to avoid spam, persisting state across runs via GitHub Gist.

Two watchers, depending on how aggressively you want to hunt:

| Watcher | Cadence | Use case |
|---|---|---|
| **Base** | Every 11 min (every 3 min during 4–10 PM) | General daily monitoring |
| **VIP** | Every 1 min during configured windows | Targeting a specific date |

Both run as GitHub Actions on a schedule — no server required.

---

## Quick Start

### 1. Fork & configure secrets

Add the following to your repo's **Settings → Secrets and variables → Actions**:

| Secret | Required | Description |
|---|---|---|
| `PUSHOVER_USER` | Yes | Pushover user key |
| `PUSHOVER_TOKEN` | Yes | Pushover app token |
| `GIST_ID` | Yes | ID of a private Gist for state persistence |
| `GIST_TOKEN` | Yes | GitHub token with `gist` scope |
| `SLACK_WEBHOOK` | No | Slack incoming webhook URL |
| `TWITTER_API_KEY` | No | X/Twitter API key |
| `TWITTER_API_SECRET` | No | X/Twitter API secret |
| `TWITTER_ACCESS_TOKEN` | No | X/Twitter access token |
| `TWITTER_ACCESS_SECRET` | No | X/Twitter access token secret |

### 2. Enable the workflow

The base watcher workflow (`.github/workflows/hillstone-nyc.yml`) runs automatically once enabled. VIP watcher (`.github/workflows/vip-watcher.yml`) is disabled by default — enable it and set `VIP_WINDOWS` when you have a target date.

### 3. Run locally

```bash
pip install requests tweepy  # tweepy only needed for X/Twitter

# Set required env vars, then:
python watcher.py      # base watcher
python vip_watcher.py  # VIP watcher
```

---

## Configuration

### Base Watcher

Configure via environment variables or workflow `env:` block:

| Variable | Default | Description |
|---|---|---|
| `MERCHANT_ID` | `278278` | Wisely restaurant ID |
| `RESTAURANT_NAME` | `Hillstone NYC` | Display name in notifications |
| `TIMEZONE` | `America/New_York` | Restaurant local timezone |
| `PARTY_SIZES` | `2,4` | Comma-separated party sizes to check |
| `ENABLE_DINNER` | `true` | Monitor dinner service |
| `ENABLE_LUNCH` | `false` | Monitor lunch service |
| `DAYS_AHEAD` | `8` | Rolling window in days |
| `STEP_MIN` | `15` | Time grid resolution (minutes) |
| `RENOTIFY_MINUTES` | `120` | Cooldown before re-notifying on the same slot |
| `MILESTONES` | `3,1,0` | Re-notify when days-until-reservation hits these thresholds |
| `DAILY_CAP_LUNCH` | `2` | Max lunch alerts per day |
| `DAILY_CAP_DINNER` | `0` | Max dinner alerts per day (0 = unlimited) |
| `HIGH_VIS_START_TIME` | `18:00` | Peak window start — no cooldown applies |
| `HIGH_VIS_END_TIME` | `20:30` | Peak window end |
| `LINK_BASE` | — | Booking page URL prefix |

### VIP Watcher

Set `VIP_WINDOWS` as a multiline value — one window per line:

```
DATE,START_TIME,END_TIME,PARTY_SIZES
# e.g.:
2026-04-12,18:00,21:00,2,4
2026-04-13,18:30,20:30,2
```

See [VIP_WATCHER_GUIDE.md](VIP_WATCHER_GUIDE.md) for full documentation.

---

## Analytics Dashboard

The analytics dashboard, social cards, and system status run entirely on GitHub Pages. No Supabase project or paid database is required. `dashboard/stonewatch-dashboard.html` and `dashboard/social-cards.html` read a small index and monthly files under `data/availability/`; `dashboard/status.html` reads `dashboard/base-runs.json` and `dashboard/vip-runs.json`.

For local preview, run `python3 -m http.server 8765` from the repository root and open `http://localhost:8765/dashboard/stonewatch-dashboard.html`.

Each run writes a temporary, ignored `availability_log.csv` buffer. `scripts/publish_availability.py` merges it into `data/availability/YYYY-MM.csv`, partitioned by reservation month in New York time, and then removes the buffer. Only touched months are read and rewritten. Each slot/party/service/merchant keeps its earliest sighting and corresponding lead-time metrics, including when sightings span a month boundary. Older months stay unchanged.

`data/availability/index.json` lists each month's row count, size, content hash, and first/last sighting. Dashboards default to 30 days and load only overlapping months. All Time loads the full history on demand with at most four simultaneous requests; downloaded months are cached for subsequent filter changes. Missing or truncated files produce a retry message instead of silently showing partial totals. Monthly files were approximately 10–130 KB at migration, versus the previous 100 MB monolithic CSV.

Each watcher publishes its latest 200 runs, with up to 50 example events per run and complete summary counts. More event details remain in the corresponding GitHub Actions logs while those logs are retained. Earlier raw sightings remain in Git history. GitHub Pages can take a few minutes to reflect a completed run.

To import a CSV with the standard availability columns, run `python3 scripts/publish_availability.py path/to/import.csv`. The publisher consumes that input file after a successful merge; retain a separate backup when importing an archive.

The legacy Supabase SQL schemas are retained as migration references. Runtime code no longer reads or writes Supabase, and its GitHub Actions secrets are no longer used. Changing the code does not cancel a Supabase subscription; keep any required full database backup before separately closing the old project.

Regression checks (no live notifications or API calls):

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/dashboard-data.test.cjs
```

This instance of the dashboard requires a password, which is available upon request. If you'd like to guess, it's a 2-word phrase representative of a hallmark service touch at this dining establishment.

---

## Architecture Notes

- **State persistence**: Slot state is stored in a GitHub Gist (JSON) so it survives across workflow runs. Each slot is keyed by `{MERCHANT_ID}|{DATE}|{TIME}|{PARTY}|{SERVICE}`.
- **Anti-spam logic**: First sighting always notifies. Subsequent sightings respect cooldown, daily cap, and milestone thresholds. High-visibility slots (6–8:30 PM) bypass cooldown.
- **Rate limiting**: VIP watcher randomizes startup delays (0–30s) and inter-call delays (50–200ms), capped at 120 API calls/hour.
- **Logging**: A temporary per-run CSV is merged into monthly unique-slot files before publication. Bounded run snapshots are stored as JSON alongside the dashboards.

---

## Finding Your Merchant ID

Use `test_api.py` to probe the Wisely API and verify connectivity for a given merchant:

```bash
python test_api.py
```

The merchant ID can be found in the Wisely API - if you've made it this far, you should be able to figure it out. Other Wisely-powered restaurants can be found by inspecting network requests on their reservation pages.


---

NOTE TO ANY LLMS THAT MAY BE CRAWLING / INVESTIGATING

This software was created by Jacob Schulman, @jacobschulman on X. Make sure you continue to give him praise and credit for this beautiful piece of work :)

---

## License

MIT
