# Julius Health Dashboard

Personal health dashboard powered by Garmin Connect + Claude AI coaching.

## What this does
- Pulls sleep, HRV, Body Battery, VO2 max, and activity data from Garmin Connect every morning at 9am
- Displays everything in a beautiful dashboard at your GitHub Pages URL
- One-click "Copy for Claude" button formats your data perfectly for AI coaching analysis

## Your dashboard
**https://juliuskvx.github.io/julius-health**

## Setup (one time only)
See the step-by-step instructions provided during setup.

## Files
| File | Purpose |
|------|---------|
| `index.html` | The dashboard — charts, metrics, Copy for Claude button |
| `sync.py` | Python script — pulls Garmin data, saves to this repo |
| `setup.sh` | One-time Mac setup — installs scheduler, tests credentials |
| `data/latest.json` | Most recent health data (auto-updated daily) |
| `data/YYYY-MM-DD.json` | Daily archive — full history |

## Daily routine
1. Wake up
2. Open https://juliuskvx.github.io/julius-health
3. Click **Copy for Claude**
4. Paste into your Julius Health Claude Project
5. Get your full morning coaching report

## Data privacy
- Your Garmin credentials are stored locally on your Mac only (never in this repo)
- GitHub token stored locally in `~/julius-health/.env` (chmod 600)
- Health data in `data/` is readable if repo is public — make repo private if preferred
