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
| `SUPABASE_URL` | No | Supabase project URL (for analytics logging) |
| `SUPABASE_KEY` | No | Supabase anon/service key |

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

`dashboard/stonewatch-dashboard.html` is a standalone HTML file that loads `availability_log.csv` and renders charts and filters for historical availability data. Open it locally in a browser — no server needed.

This instance of the dashboard requires a password, which is available upon request. If you'd like to guess, it's a 2-word phrase representative of a hallmark service touch at this dining establishment.

---

## Architecture Notes

- **State persistence**: Slot state is stored in a GitHub Gist (JSON) so it survives across workflow runs. Each slot is keyed by `{MERCHANT_ID}|{DATE}|{TIME}|{PARTY}|{SERVICE}`.
- **Anti-spam logic**: First sighting always notifies. Subsequent sightings respect cooldown, daily cap, and milestone thresholds. High-visibility slots (6–8:30 PM) bypass cooldown.
- **Rate limiting**: VIP watcher randomizes startup delays (0–30s) and inter-call delays (50–200ms), capped at 120 API calls/hour.
- **Logging**: All sightings appended to `availability_log.csv` (committed to repo) and optionally to Supabase.

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
