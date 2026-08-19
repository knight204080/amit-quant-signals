#!/bin/bash
# Daily signal generation + commit + push, then sync to the public dashboard repo
# to trigger a Vercel redeploy. Run via cron at 00:10 UTC.
set -e
cd ~/amit-quant-system
source venv/bin/activate

echo "=== $(date -u) ===" >> daily_run.log
python3 pipeline/refresh_data.py >> daily_run.log 2>&1 || echo "data refresh failed, continuing with existing data" >> daily_run.log
python3 pipeline/generate_signal.py >> daily_run.log 2>&1

git add signals.jsonl daily_run.log universe_snapshot.json
git commit -q -m "Signal: $(date -u +%Y-%m-%d)" || echo "nothing to commit" >> daily_run.log
git push -q origin main >> daily_run.log 2>&1 || echo "signals repo push failed" >> daily_run.log

# Sync the fresh signal into the dashboard repo and push -> auto-triggers Vercel redeploy
DASH=~/amit-quant-system/dashboard-repo
if [ -d "$DASH" ]; then
  cd "$DASH"
  git pull -q origin main >> ../daily_run.log 2>&1 || echo "dashboard repo pull failed" >> ../daily_run.log
  cp ~/amit-quant-system/signals.jsonl site/content/system/signals.jsonl
  cp ~/amit-quant-system/universe_snapshot.json site/content/system/universe_snapshot.json
  git add site/content/system/signals.jsonl site/content/system/universe_snapshot.json
  git commit -q -m "Sync daily signal: $(date -u +%Y-%m-%d)" || echo "dashboard: nothing to sync" >> ../daily_run.log
  git push -q origin main >> ../daily_run.log 2>&1 || echo "dashboard repo push failed" >> ../daily_run.log
fi
