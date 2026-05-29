#!/bin/sh
# MobiCast startup entrypoint
# Verifies required reference files are present before launching the app.
# Exits with a clear error message if any file is missing.
# On success, hands off to gunicorn via exec (replaces the shell process).

DEFAULTS_DIR="/app/data/defaults"
MISSING=0

echo "[MobiCast] Checking reference files in $DEFAULTS_DIR..."

# OECD file: any file whose name starts with 'oecd_scholarships' (case-insensitive)
OECD_COUNT=$(ls "$DEFAULTS_DIR" 2>/dev/null | grep -i "^oecd_scholarships" | wc -l)
if [ "$OECD_COUNT" -eq 0 ]; then
  echo "[MobiCast] ERROR: No OECD file found in data/defaults/."
  echo "[MobiCast]        Expected a file named oecd_scholarships.csv (or .CSV)"
  MISSING=1
fi

# Erasmus+ files: at least one file matching the pattern must be present (any extension)
ERASMUS_COUNT=$(ls "$DEFAULTS_DIR"/ErasmusPlus_KA1_* 2>/dev/null | wc -l)
if [ "$ERASMUS_COUNT" -eq 0 ]; then
  echo "[MobiCast] ERROR: No Erasmus+ file found in data/defaults/."
  echo "[MobiCast]        Expected at least one file named ErasmusPlus_KA1_*"
  MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
  echo ""
  echo "[MobiCast] -------------------------------------------------------"
  echo "[MobiCast] Place the required files in data/defaults/ and restart."
  echo "[MobiCast] See README.md for the list of expected files."
  echo "[MobiCast] -------------------------------------------------------"
  exit 1
fi

echo "[MobiCast] All reference files found. Starting application..."
exec gunicorn --workers 2 --bind 0.0.0.0:8050 app:server
