#!/usr/bin/env bash
# One backup run: PostgreSQL (pg_dump custom format) + media (tar.gz), checksums, optional encryption,
# rotation 7 daily / 4 weekly / 12 monthly, optional off-site copy (rclone), status file for the admin.
# Usage: backup.sh [auto|manual] [label]
#   auto   (default, scheduler): daily, plus weekly on Sunday and monthly on the 1st
#   manual (make backup, before a rebuild or a restore): kept apart, the last BACKUP_KEEP_MANUAL are kept
source /usr/local/bin/backup-lib.sh

mode="${1:-auto}"
label="${2:-}"
[[ "$mode" == "auto" || "$mode" == "manual" ]] || die "mode inconnu : $mode (auto|manual)"
if [[ "${BACKUP_REQUIRE_ENCRYPTION:-0}" == "1" ]] && ! encryption_enabled; then
  die "BACKUP_REQUIRE_ENCRYPTION=1 mais BACKUP_PASSPHRASE est vide : aucune sauvegarde en clair n'est produite"
fi

mkdir -p "$BACKUP_ROOT"
exec 9>"$BACKUP_ROOT/.lock"
flock -n 9 || die "une sauvegarde est déjà en cours"

stamp="$(date '+%Y-%m-%d_%H%M%S')"
[[ -n "$label" ]] && stamp="${stamp}_$(echo "$label" | tr -cd 'a-zA-Z0-9-' | cut -c1-24)"
work="$BACKUP_ROOT/.tmp-$stamp"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work"
started=$(date +%s)

wait_for_db
log "base $PGDATABASE → db.dump"
pg_dump --format=custom --compress=6 --no-owner --no-privileges -f "$work/db.dump"
pg_restore --list "$work/db.dump" >/dev/null || die "le fichier db.dump produit est illisible"
tables=$(psql -Atc "select count(*) from information_schema.tables where table_schema='public'")
users=$(psql -Atc "select count(*) from accounts_user" 2>/dev/null || echo 0)
profiles=$(psql -Atc "select count(*) from profiles_profile" 2>/dev/null || echo 0)

media_files=0
if [[ -d "$MEDIA_DIR" ]]; then
  media_files=$(find "$MEDIA_DIR" -type f | wc -l)
  log "médias $MEDIA_DIR ($media_files fichiers) → media.tar.gz"
  tar -C "$MEDIA_DIR" -czf "$work/media.tar.gz" .
  tar -tzf "$work/media.tar.gz" >/dev/null || die "l'archive media.tar.gz produite est illisible"
fi

cat >"$work/manifest.json" <<JSON
{
  "stamp": "$stamp",
  "mode": "$mode",
  "created_at": "$(date -Iseconds)",
  "database": "$PGDATABASE",
  "postgres_server": "$(psql -Atc 'show server_version')",
  "pg_dump": "$(pg_dump --version | awk '{print $3}')",
  "tables": $tables,
  "users": $users,
  "profiles": $profiles,
  "media_files": $media_files,
  "encrypted": $(encryption_enabled && echo true || echo false)
}
JSON

if encryption_enabled; then
  log "chiffrement AES-256 (gpg)"
  for f in db.dump media.tar.gz; do
    [[ -f "$work/$f" ]] || continue
    gpg --batch --quiet --yes --pinentry-mode loopback --passphrase "$BACKUP_PASSPHRASE" \
      --symmetric --cipher-algo AES256 --compress-algo none -o "$work/$f.gpg" "$work/$f"
    rm -f "$work/$f"
  done
fi
(cd "$work" && sha256sum -- * >SHA256SUMS)

# Publish atomically, then copy into the weekly / monthly tiers when due.
if [[ "$mode" == "manual" ]]; then tiers=(manual); else tiers=(daily); fi
if [[ "$mode" == "auto" ]]; then
  [[ "$(date +%u)" == "7" ]] && tiers+=(weekly)
  [[ "$(date +%d)" == "01" ]] && tiers+=(monthly)
fi
first="${tiers[0]}"
mkdir -p "$BACKUP_ROOT/$first"
mv "$work" "$BACKUP_ROOT/$first/$stamp"
trap - EXIT
for tier in "${tiers[@]:1}"; do
  mkdir -p "$BACKUP_ROOT/$tier"
  cp -a "$BACKUP_ROOT/$first/$stamp" "$BACKUP_ROOT/$tier/$stamp"
done

# Rotation: keep the N most recent of each tier.
for tier in "${TIERS[@]}"; do
  [[ -d "$BACKUP_ROOT/$tier" ]] || continue
  keep=$(keep_for "$tier")
  find "$BACKUP_ROOT/$tier" -mindepth 1 -maxdepth 1 -type d ! -name '.*' -printf '%f\n' | sort -r | tail -n "+$((keep + 1))" |
    while read -r old; do
      log "rotation : suppression de $tier/$old"
      rm -rf "${BACKUP_ROOT:?}/$tier/$old"
    done
done
find "$BACKUP_ROOT" -maxdepth 1 -name '.tmp-*' -mmin +360 -exec rm -rf {} + 2>/dev/null || true

size=$(du -sb "$BACKUP_ROOT/$first/$stamp" | cut -f1)
duration=$(( $(date +%s) - started ))

offsite="disabled"
if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  log "copie hors site → $RCLONE_REMOTE"
  if rclone sync "$BACKUP_ROOT" "$RCLONE_REMOTE" --exclude '.tmp-*/**' --exclude '.lock' --exclude 'last_success.json' \
       --exclude 'last_verify.json' --transfers 2 --retries 5 --low-level-retries 10 2>&1 | tail -n 5 >&2; then
    offsite="ok"
  else
    offsite="failed"
    log "ATTENTION : la copie hors site a échoué (la sauvegarde locale est faite)"
  fi
fi

cat >"$BACKUP_ROOT/last_success.json" <<JSON
{"stamp": "$stamp", "path": "$first/$stamp", "finished_at": "$(date -Iseconds)", "epoch": $(date +%s), "size_bytes": $size, "duration_s": $duration, "users": $users, "profiles": $profiles, "media_files": $media_files, "encrypted": $(encryption_enabled && echo true || echo false), "offsite": "$offsite"}
JSON
chmod 644 "$BACKUP_ROOT/last_success.json"
log "OK $first/$stamp ($(numfmt --to=iec "$size"), ${duration}s, $users comptes, $profiles pages, $media_files médias, hors site : $offsite)"
echo "$first/$stamp"
