#!/usr/bin/env bash
# Healthy when the last successful backup is younger than BACKUP_MAX_AGE_HOURS (default 26 h).
f="${BACKUP_ROOT:-/backups}/last_success.json"
[[ -f "$f" ]] || exit 1
last=$(sed -n 's/.*"epoch": \([0-9]*\).*/\1/p' "$f")
[[ -n "$last" ]] || exit 1
(( $(date +%s) - last < ${BACKUP_MAX_AGE_HOURS:-26} * 3600 ))
