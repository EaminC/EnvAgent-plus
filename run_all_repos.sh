#!/usr/bin/env bash

# Run EnvAgent-plus provisioning sequentially for a list of GitHub repos.
# 
# Features:
# - Reads repos from repos.txt (one per line, # comments and blanks ignored)
# - Runs: python 2.0/src/provision_v2.py --repo "$url" --site <site>
# - Logs to logs_<site>/<timestamp>_<safe_repo_name>.log
# - Appends to summary.csv: repo_url,exit_code,start_time,end_time,duration_seconds,log_path
# - Sequential processing, continues on failures, records all results
# 
# IMPORTANT: NEW FALLBACK STRATEGY (v2.0)
# - Automatic fallback to alternative node types if primary unavailable
# - Reduced-duration retries (e.g., 48h → 24h)
# - KVM (VM-based) fallback if bare metal exhausted
# - ~95%+ success rate on small workloads
# - See FALLBACK_STRATEGY.md for details
#
# Usage:
#   ./run_all_repos.sh                  # Uses default site (uc)
#   SITE=tacc ./run_all_repos.sh        # Use TACC site
#   REPOS_FILE=my_repos.txt ./run_all_repos.sh

set -euo pipefail

REPOS_FILE="${REPOS_FILE:-repos.txt}"
SITE="${SITE:-uc}"
LOG_DIR="${LOG_DIR:-logs_${SITE}}"
SUMMARY_FILE="${LOG_DIR}/summary.csv"

mkdir -p "$LOG_DIR"

# Ensure summary header exists
if [[ ! -f "$SUMMARY_FILE" ]]; then
  echo "repo_url,exit_code,start_time,end_time,duration_seconds,log_path" > "$SUMMARY_FILE"
fi

if [[ ! -f "$REPOS_FILE" ]]; then
  echo "$REPOS_FILE not found. Create it or run ./make_repos_txt_example.sh" >&2
  exit 1
fi

# Load repos, ignoring blanks and comments, normalizing CRLF
mapfile -t REPOS < <(sed -e 's/#.*$//' -e '/^\s*$/d' "$REPOS_FILE" | tr -d '\r')
TOTAL=${#REPOS[@]}

if (( TOTAL == 0 )); then
  echo "No repos found in $REPOS_FILE (after filtering comments/blanks)." >&2
  exit 1
fi

safe_name() {
  local url="$1"
  # Use last two path segments (owner_repo), strip .git, replace non-safe chars with _
  local name
  name=$(echo "$url" | awk -F'/' '{n=NF; if($n=="") n=NF-1; print $(n-1)"_"$n}' | sed -E 's/\.git$//; s/[^A-Za-z0-9._-]+/_/g')
  echo "$name"
}

for (( i=0; i< TOTAL; i++ )); do
  url="${REPOS[$i]}"
  idx=$((i+1))
  echo "[$idx/$TOTAL] $url"

  ts=$(date +%Y%m%d_%H%M%S)
  name=$(safe_name "$url")
  log_path="$LOG_DIR/${ts}_${name}.log"

  start_iso=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  start_epoch=$(date +%s)

  echo "Command: python 2.0/src/provision_v2.py --repo \"$url\" --site $SITE" | tee -a "$log_path"
  echo "Start:   $start_iso" | tee -a "$log_path"

  # Run the provisioning, capturing the python exit code while still tee-ing logs
  set +e
  python 2.0/src/provision_v2.py --repo "$url" --site "$SITE" --key-path ~/.ssh/id_rsa.pub 2>&1 | tee -a "$log_path"
  exit_code=${PIPESTATUS[0]}
  set -e

  end_iso=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  end_epoch=$(date +%s)
  duration=$(( end_epoch - start_epoch ))

  echo "End:     $end_iso (exit=$exit_code, duration=${duration}s)" | tee -a "$log_path"

  # Append CSV row
  echo "$url,$exit_code,$start_iso,$end_iso,$duration,$log_path" >> "$SUMMARY_FILE"

  # Small pause between repos to avoid API bursts
  sleep 5

done

echo "All done. Summary: $SUMMARY_FILE"