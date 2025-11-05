# VIP Watcher Guide

The VIP Watcher allows you to monitor specific date/time windows with high frequency (every 1 minute) for hard-to-get reservations.

## Quick Start

### 1. Set Up Pushover Credentials (Optional but Recommended)

For VIP-specific notifications, create separate Pushover credentials:

1. Go to GitHub Settings → Secrets → Actions
2. Add these secrets:
   - `PUSHOVER_USER_VIP` - Your Pushover user key (can be same as base monitor)
   - `PUSHOVER_TOKEN_VIP` - Your Pushover app token (can be same or different)
   - `GIST_ID_VIP` - Create a new Gist for VIP state tracking (recommended to keep separate)

**Note:** You can reuse your existing `PUSHOVER_USER_HILLSTONE_NYC` and `PUSHOVER_TOKEN_HILLSTONE_NYC` if you want VIP alerts to go to the same place. Just update the workflow to use those secret names instead.

### 2. Add VIP Windows

Edit [`.github/workflows/vip-watcher.yml`](.github/workflows/vip-watcher.yml) and add your target dates/times:

```yaml
VIP_WINDOWS: |
  2025-11-15,18:00,20:00,2,4
  2025-11-22,19:00,21:00,2
```

**Format:** `DATE,START_TIME,END_TIME,PARTY_SIZES...`

- **DATE**: `YYYY-MM-DD` (e.g., `2025-11-15`)
- **START_TIME**: `HH:MM` in 24-hour format (e.g., `18:00` = 6 PM)
- **END_TIME**: `HH:MM` in 24-hour format (e.g., `20:00` = 8 PM)
- **PARTY_SIZES**: Comma-separated party sizes to check (e.g., `2,4` checks both party of 2 and 4)

**Times are in restaurant timezone (America/New_York).**

### 3. Commit and Push

```bash
git add .github/workflows/vip-watcher.yml
git commit -m "Add VIP windows for upcoming dates"
git push
```

The workflow will start running every minute automatically.

## Examples

### Single Date, Single Party Size
```yaml
VIP_WINDOWS: |
  2025-11-15,18:00,20:00,2
```
Checks for party of 2 between 6-8 PM on November 15.

### Multiple Dates
```yaml
VIP_WINDOWS: |
  2025-11-15,18:00,20:00,2,4
  2025-11-20,19:00,21:00,2
  2025-11-22,17:30,19:30,4
```
Monitors three different date/time windows simultaneously.

### Lunch Reservation
```yaml
VIP_WINDOWS: |
  2025-11-18,12:00,13:30,2
```
Checks for lunch reservations (11:15 AM - 2:00 PM window).

## How It Works

1. **Every minute**, the workflow runs
2. It checks if any VIP windows are **active** (current time hasn't passed the end time yet)
3. For each active window:
   - Probes the API every 15 minutes within your specified time range
   - Checks all party sizes you specified
   - Adds random delays (50-200ms) between API calls to avoid detection
4. When a slot is found:
   - Sends immediate notification via Pushover (with distinct sound/priority)
   - Won't notify again for the same slot for 5 minutes (to avoid spam)
5. **Auto-expires** after the end time passes (no manual cleanup needed)

## Managing VIP Windows

### Adding a New Window
1. Edit [`.github/workflows/vip-watcher.yml`](.github/workflows/vip-watcher.yml)
2. Add a new line to `VIP_WINDOWS:`
3. Commit and push

### Removing a Window
1. Delete the line from `VIP_WINDOWS:`
2. Commit and push

**Tip:** Leave expired windows in place - they auto-expire and will be ignored.

### Temporarily Disabling All VIP Checks
Comment out all lines with `#`:
```yaml
VIP_WINDOWS: |
  # 2025-11-15,18:00,20:00,2,4
  # 2025-11-22,19:00,21:00,2
```

## Safety Features

- **Rate limiting**: Max 120 API calls per hour (safety cap)
- **Randomization**: Random 0-30s startup delay + 50-200ms between calls
- **Auto-expiration**: Windows stop checking after end time passes
- **Separate state**: VIP notifications don't interfere with base monitor
- **Short cooldown**: 5-minute cooldown per slot (vs 3 hours for base monitor)

## Differences from Base Monitor

| Feature | Base Monitor | VIP Watcher |
|---------|-------------|-------------|
| Frequency | 11 min (3 min peak) | 1 minute |
| Scope | Rolling 8-day window | Specific dates/times only |
| Notifications | 3-hour cooldown | 5-minute cooldown |
| State | `seen_{merchant_id}.json` | `vip_{merchant_id}.json` |
| Pushover Sound | Default | "magic" |
| Priority | Normal (0) | High (1) |
| Expiration | Continuous | Auto-expires |

Both systems run independently - you can have VIP windows AND the base monitor active simultaneously.

## Troubleshooting

### No notifications received
1. Check GitHub Actions logs: Actions tab → "vip-watcher" workflow
2. Verify `PUSHOVER_USER_VIP` and `PUSHOVER_TOKEN_VIP` secrets are set
3. Check if VIP windows are formatted correctly
4. Ensure date hasn't passed yet

### Too many notifications
1. Increase the cooldown in `vip_watcher.py` (line 316: `min_gap = 5 * 60`)
2. Consider using the base monitor for less urgent searches

### Workflow not running
1. Check if VIP_WINDOWS is empty (workflow still runs but does nothing)
2. Verify the workflow file is in `.github/workflows/`
3. Check for YAML syntax errors

## Advanced Configuration

Edit [`vip_watcher.py`](vip_watcher.py) to customize:

- **Notification cooldown** (line 316): Change `min_gap = 5 * 60` (seconds)
- **Random stagger range** (workflow): Adjust `RANDOM_STAGGER_MS: "50,200"`
- **Max API calls per hour** (workflow): Adjust `MAX_CHECKS_PER_HOUR: "120"`
- **Time grid resolution** (workflow): Change `STEP_MIN: "15"` (minutes)

## Example Workflow

You want a table on **Friday, November 15** between **6-8 PM** for a party of 2:

1. Edit `.github/workflows/vip-watcher.yml`:
```yaml
VIP_WINDOWS: |
  2025-11-15,18:00,20:00,2
```

2. Commit and push:
```bash
git add .github/workflows/vip-watcher.yml
git commit -m "VIP: monitoring Nov 15 6-8 PM"
git push
```

3. The system will:
   - Start checking every minute
   - Probe the API at 6:00, 6:15, 6:30, 6:45, 7:00, 7:15, 7:30, 7:45, 8:00 PM
   - Send instant notification if a slot opens
   - Auto-stop after 8:00 PM on Nov 15

4. When you see the notification:
   - Click the link immediately
   - Book the reservation
   - (Optional) Remove the VIP window from the config

That's it! The base monitor continues running for general availability while your VIP watcher targets your specific date.
