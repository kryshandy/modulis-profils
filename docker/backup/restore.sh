#!/usr/bin/env bash
# Restore a backup into the running database and the media volume.
# Usage: restore.sh <latest|stamp|tier/stamp> [--db-only|--media-only] [--no-safety-backup] --yes
# The web and worker services must be stopped (make restore does it). A safety backup of the current
# state is taken first, so a restore can itself be undone.
source /usr/local/bin/backup-lib.sh

ref="latest"; what="all"; safety=1; confirmed=0
for arg in "$@"; do
  case "$arg" in
    --db-only) what="db" ;;
    --media-only) what="media" ;;
    --no-safety-backup) safety=0 ;;
    --yes) confirmed=1 ;;
    -*) die "option inconnue : $arg" ;;
    *) ref="$arg" ;;
  esac
done
dir="$(resolve_backup "$ref")"
[[ "$confirmed" == "1" ]] || die "restauration de $dir : ajoutez --yes pour confirmer (les données actuelles seront remplacées)"

log "vérification des empreintes de $dir"
check_sums "$dir"
wait_for_db

if [[ "$safety" == "1" ]]; then
  log "sauvegarde de sécurité de l'état actuel avant restauration"
  /usr/local/bin/backup.sh manual avant-restauration >/dev/null
fi

work="$(mktemp -d "$BACKUP_ROOT/.tmp-restore-XXXXXX")"
trap 'rm -rf "$work"' EXIT

if [[ "$what" != "media" ]]; then
  dump="$(plain_file "$dir" db.dump "$work")"
  [[ -n "$dump" ]] || die "db.dump absent de $dir"
  log "restauration de la base $PGDATABASE"
  psql -q -v ON_ERROR_STOP=1 -d postgres -c \
    "select pg_terminate_backend(pid) from pg_stat_activity where datname = '$PGDATABASE' and pid <> pg_backend_pid();" >/dev/null
  psql -q -v ON_ERROR_STOP=1 -d postgres -c "drop database if exists \"$PGDATABASE\" with (force);"
  psql -q -v ON_ERROR_STOP=1 -d postgres -c "create database \"$PGDATABASE\";"
  pg_restore --no-owner --no-privileges --exit-on-error -d "$PGDATABASE" "$dump"
  log "base restaurée : $(psql -Atc 'select count(*) from accounts_user') comptes, $(psql -Atc 'select count(*) from profiles_profile') pages"
fi

if [[ "$what" != "db" ]]; then
  archive="$(plain_file "$dir" media.tar.gz "$work")"
  if [[ -n "$archive" ]]; then
    log "restauration des médias dans $MEDIA_DIR"
    mkdir -p "$MEDIA_DIR"
    find "$MEDIA_DIR" -mindepth 1 -delete
    tar -C "$MEDIA_DIR" -xzf "$archive"
    chown -R "${MEDIA_UID:-1000}:${MEDIA_GID:-1000}" "$MEDIA_DIR" 2>/dev/null || true
    log "médias restaurés : $(find "$MEDIA_DIR" -type f | wc -l) fichiers"
  else
    log "pas d'archive de médias dans cette sauvegarde"
  fi
fi
log "restauration terminée depuis $dir"
