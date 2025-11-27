#!/usr/bin/env bash
# Fail fast: exit on error, undefined vars, or failed pipes
set -euo pipefail

# Resolve the directory where this script lives
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Backend root is the parent directory of /scripts
BACKEND="$(dirname "$SCRIPT_DIR")"

# Path to the virtualenv used by the Plone backend
VENV="$BACKEND/.venv"

# Zope/Plone helper binaries from the virtualenv
ZCONSOLE="$VENV/bin/zconsole"
RUNWSGI="$VENV/bin/runwsgi"

# Zope config for zconsole (ZConfig format)
ZOPE_CONF="$BACKEND/instance/etc/zope.conf"
# Zope config for runwsgi (INI format)
ZOPE_INI="$BACKEND/instance/etc/zope.ini"

# Python script that performs the WebP conversion
SCRIPT="$BACKEND/scripts/convert_images_to_webp.py"

# Log file for this cron-driven job
LOGFILE="$BACKEND/var/log/webp_cron.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOGFILE")"

echo "--------------------------------------------------" >> "$LOGFILE"
echo "$(date '+%Y-%m-%d %H:%M:%S')  WebP CRON JOB START" >> "$LOGFILE"

echo "Stopping backend..." >> "$LOGFILE"

# Find the runwsgi process that uses zope.ini (if any)
PID=$(pgrep -f "runwsgi.*zope.ini" || true)

if [ -n "$PID" ]; then
    # Gracefully kill the running backend
    echo "Killing runwsgi PID: $PID" >> "$LOGFILE"
    kill "$PID"
    sleep 3
else
    # Nothing to stop – backend is already down
    echo "Backend not running (no PID found)." >> "$LOGFILE"
fi

echo "Running WebP converter..." >> "$LOGFILE"

# Allow overriding DRY_RUN and QUALITY from the environment
DRY_RUN="${DRY_RUN:-0}"
QUALITY="${QUALITY:-85}"

# Run the conversion script via zconsole inside the Plone app
DRY_RUN="$DRY_RUN" QUALITY="$QUALITY" \
  "$ZCONSOLE" run "$ZOPE_CONF" "$SCRIPT" >> "$LOGFILE" 2>&1

echo "Restarting backend..." >> "$LOGFILE"
# Restart backend in the background using runwsgi
"$RUNWSGI" "$ZOPE_INI" >> "$LOGFILE" 2>&1 &
sleep 3

echo "$(date '+%Y-%m-%d %H:%M:%S')  WebP CRON JOB END" >> "$LOGFILE"
echo "--------------------------------------------------" >> "$LOGFILE"
