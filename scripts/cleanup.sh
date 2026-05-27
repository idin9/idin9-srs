#!/usr/bin/env bash
#
# Cleanup script for idin9-srs
# Run via cron to delete recordings older than retention policy.
#
# Usage:
#   ./scripts/cleanup.sh [path-to-project]
#
# Add to crontab (run daily at 3am):
#   0 3 * * * /path/to/idin9-srs/scripts/cleanup.sh /path/to/idin9-srs >> /var/log/siprec-cleanup.log 2>&1
#

set -euo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR"

if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found in $PROJECT_DIR"
    exit 1
fi

# Source .env to get INDEX_DB and RETENTION_YEARS
export $(grep -v '^\s*#' .env | grep -v '^\s*$' | xargs)

if [ -z "${RETENTION_YEARS:-}" ]; then
    RETENTION_YEARS=7
fi

OUTPUT_DIR="${OUTPUT_DIR:-recordings}"
INDEX_DB="${INDEX_DB:-index.db}"
DB_PATH="$OUTPUT_DIR/$INDEX_DB"

if [ ! -f "$DB_PATH" ]; then
    echo "Index database not found at $DB_PATH — nothing to clean up."
    exit 0
fi

echo "=== SIPREC Cleanup: $(date) ==="
echo "Project: $PROJECT_DIR"
echo "Retention: ${RETENTION_YEARS} years"
echo "Database: $DB_PATH"

# Instead of running full Python with dependencies just for cleanup,
# we check by file modification time on WAV files older than retention years.
# This is a lightweight alternative.

cutoff_seconds=$((RETENTION_YEARS * 365 * 24 * 60 * 60))
now_seconds=$(date +%s)
deleted_count=0

if [ -d "$OUTPUT_DIR" ]; then
    find "$OUTPUT_DIR" -maxdepth 1 -name "*.wav" -type f 2>/dev/null | while read -r wav_file; do
        file_seconds=$(stat -c %Y "$wav_file" 2>/dev/null || stat -f %m "$wav_file" 2>/dev/null)
        age_seconds=$((now_seconds - file_seconds))
        if [ $age_seconds -gt $cutoff_seconds ]; then
            echo "Deleting: $wav_file (age: $((age_seconds / 86400)) days)"
            rm -f "$wav_file"
            deleted_count=$((deleted_count + 1))
        fi
    done
fi

echo "Deleted $deleted_count old WAV files."
echo "=== Cleanup complete ==="
