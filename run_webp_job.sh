#!/usr/bin/env bash
set -euo pipefail

# Directory of this script (…/backend/scripts)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Backend root (…/backend)
BACKEND="$(dirname "$SCRIPT_DIR")"

# Virtualenv & binaries (override via env if needed)
VENV="${VENV:-"$BACKEND/.venv"}"
ZCONSOLE="${ZCONSOLE:-"$VENV/bin/zconsole"}"
RUNWSGI="${RUNWSGI:-"$VENV/bin/runwsgi"}"

# Zope configs (override via env if needed)
ZOPE_CONF="${ZOPE_CONF:-"$BACKEND/instance/etc/zope.conf"}"
ZOPE_INI="${ZOPE_INI:-"$BACKEND/instance/etc/zope.ini"}"

# Python script that performs the WebP conversion (override via env if needed)
SCRIPT="${SCRIPT:-"$BACKEND/scripts/convert_images_to_webp.py"}"

# Log file for this cron-driven job
LOGFILE="${LOGFILE:-"$BACKEND/var/log/webp_cron.log"}"
mkdir -p "$(dirname "$LOGFILE")"

# Runtime settings (can be overridden via env / cron)
DRY_RUN="${DRY_RUN:-0}"
QUALITY="${QUALITY:-85}"
GRACE_SECONDS="${GRACE_SECONDS:-5}"

{
  echo "--------------------------------------------------"
  echo "$(date '+%Y-%m-%d %H:%M:%S')  WebP CRON JOB START"
  echo "BACKEND=$BACKEND"
  echo "DRY_RUN=$DRY_RUN"
  echo "QUALITY=$QUALITY"

  echo "Stopping backend (runwsgi)…"

  # Find the runwsgi process using this zope.ini (if any)
  PID="$(pgrep -f "runwsgi.*${ZOPE_INI##*/}" || true)"

  if [ -n "$PID" ]; then
      echo "Found runwsgi PID: $PID → stopping"
      kill "$PID"
      sleep "$GRACE_SECONDS"
  else
      echo "Backend not running (no matching runwsgi PID found)."
  fi

  echo "Running WebP converter…"
  DRY_RUN="$DRY_RUN" QUALITY="$QUALITY" \
    "$ZCONSOLE" run "$ZOPE_CONF" "$SCRIPT"

  echo "Restarting backend via runwsgi…"
  "$RUNWSGI" "$ZOPE_INI" &

  echo "$(date '+%Y-%m-%d %H:%M:%S')  WebP CRON JOB END"
  echo "--------------------------------------------------"
} >> "$LOGFILE" 2>&1
