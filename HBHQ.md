---
deploy:
  type: github-actions
  review_mode: github-actions
  merge_deploys_prod: true
actions:
  staging_label: Review PR
  ship_label: Merge to Main
  merge_label: Merge to Main
  setup_merge_label: Merge HBHQ.md
  send_back_label: Request changes
---

# Stonewatch HBHQ Contract

Stonewatch is a GitHub Actions based reservation availability monitor. It polls the Wisely API, sends notifications, and writes state/log output through Gist, CSV, Slack, Pushover, X, and optional Supabase integrations.

Each request should create a branch and PR. HBHQ should treat this as a GitHub Actions runtime project: there is no server deploy command, but merging to `main` changes what scheduled/manual workflows run.

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
