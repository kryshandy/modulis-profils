#!/usr/bin/env bash
# Prove a backup can be restored: checksums, archive readability, and a full restore of the dump into
# a throw-away database (dropped afterwards). Never touches the real database or the media volume.
# Usage: verify.sh [latest|stamp|tier/stamp]
source /usr/local/bin/backup-lib.sh

dir="$(resolve_backup "${1:-latest}")"
check_db="${PGDATABASE}_verif_restauration"
work="$(mktemp -d "$BACKUP_ROOT/.tmp-verify-XXXXXX")"
cleanup() { psql -q -d postgres -c "drop database if exists \"$check_db\" with (force);" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

log "vérification de $dir"
check_sums "$dir"
wait_for_db

dump="$(plain_file "$dir" db.dump "$work")"
[[ -n "$dump" ]] || die "db.dump absent"
psql -q -v ON_ERROR_STOP=1 -d postgres -c "drop database if exists \"$check_db\" with (force);" -c "create database \"$check_db\";"
pg_restore --no-owner --no-privileges --exit-on-error -d "$check_db" "$dump"
tables=$(psql -Atd "$check_db" -c "select count(*) from information_schema.tables where table_schema='public'")
users=$(psql -Atd "$check_db" -c "select count(*) from accounts_user")
profiles=$(psql -Atd "$check_db" -c "select count(*) from profiles_profile")
migrations=$(psql -Atd "$check_db" -c "select count(*) from django_migrations")
(( tables > 0 && migrations > 0 )) || die "la base restaurée est vide"

media=0
archive="$(plain_file "$dir" media.tar.gz "$work")"
if [[ -n "$archive" ]]; then
  media=$(tar -tzf "$archive" | grep -vc '/$' || true)
fi

cat >"$BACKUP_ROOT/last_verify.json" <<JSON
{"stamp": "$(basename "$dir")", "verified_at": "$(date -Iseconds)", "epoch": $(date +%s), "tables": $tables, "users": $users, "profiles": $profiles, "media_files": $media, "ok": true}
JSON
chmod 644 "$BACKUP_ROOT/last_verify.json"
log "OK : restauration test réussie ($tables tables, $migrations migrations, $users comptes, $profiles pages, $media médias)"
