---
deploy:
  type: none
actions:
  staging_label: No deploy
  ship_label: Merge PR
  merge_label: Merge PR
  setup_merge_label: Merge HBHQ.md
  send_back_label: Request changes
---

# Stonewatch HBHQ Contract

Stonewatch is a GitHub Actions based reservation availability monitor. It polls the Wisely API, sends notifications, and writes state/log output through Gist, CSV, Slack, Pushover, X, and optional Supabase integrations.

HBHQ should treat this as a merge-only project. There is no server deploy; GitHub Actions are the runtime.

## Build And Test

```bash
pip install requests tweepy
python test_api.py
python watcher.py
python vip_watcher.py
```

Use local environment variables or GitHub Actions secrets for real runs.

## Runtime

- Base workflow: `.github/workflows/hillstone-nyc.yml`.
- VIP workflow: `.github/workflows/vip-watcher.yml`.
- Dashboard: `dashboard/stonewatch-dashboard.html`.
- State persistence: GitHub Gist.

## Agent Notes

- Do not commit API keys, webhook URLs, tokens, or private booking details beyond what is already intentionally documented.
- Be careful with workflow schedules and notification settings; a small change can create alert spam.
- Preserve anti-spam/dedupe logic unless the request explicitly targets it.
- Keep PRs focused on the assigned HBHQ item. Do not merge your own PR.
