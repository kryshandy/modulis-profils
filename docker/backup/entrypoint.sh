#!/usr/bin/env bash
# Backup scheduler: one automatic backup a day at BACKUP_TIME (local time, default 02:30 Douala),
# a catch-up run at start when the last one is too old, and a test restore every Sunday.
# Any other command is executed as is (docker compose run --rm backup restore.sh …).
source /usr/local/bin/backup-lib.sh

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

BACKUP_TIME="${BACKUP_TIME:-02:30}"
MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"
[[ "$BACKUP_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "BACKUP_TIME invalide : $BACKUP_TIME (HH:MM)"
mkdir -p "$BACKUP_ROOT"

last_epoch() { sed -n 's/.*"epoch": \([0-9]*\).*/\1/p' "$BACKUP_ROOT/last_success.json" 2>/dev/null || true; }

run_backup() {
  if /usr/local/bin/backup.sh auto >/dev/null; then
    if [[ "$(date +%u)" == "7" || ! -f "$BACKUP_ROOT/last_verify.json" ]]; then
      /usr/local/bin/verify.sh latest || log "ATTENTION : la restauration test a échoué"
    fi
  else
    log "ATTENTION : la sauvegarde a échoué, nouvel essai dans 15 minutes"
    sleep 900
    /usr/local/bin/backup.sh auto >/dev/null || log "ATTENTION : second échec de la sauvegarde"
  fi
}

log "planificateur démarré : sauvegarde chaque jour à $BACKUP_TIME ($TZ) dans $BACKUP_ROOT," \
  "chiffrement : $(encryption_enabled && echo oui || echo non), hors site : ${RCLONE_REMOTE:-non}"
last="$(last_epoch)"
if [[ -z "$last" ]] || (( $(date +%s) - last > MAX_AGE_HOURS * 3600 )); then
  log "dernière sauvegarde absente ou trop ancienne : sauvegarde de rattrapage"
  run_backup
fi

while true; do
  now=$(date +%s)
  next=$(date -d "today $BACKUP_TIME" +%s)
  (( next <= now )) && next=$(date -d "tomorrow $BACKUP_TIME" +%s)
  log "prochaine sauvegarde : $(date -d "@$next" '+%Y-%m-%d %H:%M')"
  sleep $(( next - now ))
  run_backup
done
