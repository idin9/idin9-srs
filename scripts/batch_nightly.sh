#!/bin/bash
# -----------------------------------------------------------------------------
# Nightly Batch Generation Cron Script
# -----------------------------------------------------------------------------
# Recommended to run this via cron every night at 2:00 AM:
# 0 2 * * * /Projects/idin9-srs/scripts/batch_nightly.sh >> /var/log/idin9-srs-batch.log 2>&1
# -----------------------------------------------------------------------------

# Automatically target records from the previous 24-hour window
START_FROM=$(date -d "yesterday 00:00:00" -Iseconds --utc | sed 's/+00:00/Z/')
START_TO=$(date -d "today 00:00:00" -Iseconds --utc | sed 's/+00:00/Z/')

echo "========================================================="
echo "Starting Nightly AI Batch Generate Job"
echo "Date: $(date)"
echo "Targeting records between: $START_FROM and $START_TO"
echo "========================================================="

# Get an API token using the default admin credentials (adjust if changed)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"root","password":"rAL0bdkpo!"}' | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')

if [ -z "$TOKEN" ]; then
    echo "ERROR: Failed to authenticate to local API. Aborting batch."
    exit 1
fi

# Fire the batch-generate endpoint
RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/maintenance/batch-generate?start_time_from=${START_FROM}&start_time_to=${START_TO}&limit=10000" \
  -H "Authorization: Bearer $TOKEN")

echo "Result:"
echo "$RESPONSE" | python3 -m json.tool || echo "$RESPONSE"
echo "Done."
