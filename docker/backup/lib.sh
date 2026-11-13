#!/usr/bin/env bash
# Shared helpers of the backup service (sourced by backup.sh, restore.sh, verify.sh, list.sh, entrypoint.sh).
# Backups land in BACKUP_ROOT, a folder of the HOST bind-mounted into the container: they survive
# `docker compose down -v`, image rebuilds, volume pruning and the loss of the Docker installation.
set -Eeuo pipefail
umask 077  # backups hold personal data: owner-only files

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
MEDIA_DIR="${MEDIA_DIR:-/media}"
KEEP_DAILY="${BACKUP_KEEP_DAILY:-7}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${BACKUP_KEEP_MONTHLY:-12}"
KEEP_MANUAL="${BACKUP_KEEP_MANUAL:-10}"
TIERS=(daily weekly monthly manual)
export PGHOST="${PGHOST:-db}" PGPORT="${PGPORT:-5432}" PGUSER="${PGUSER:-modulis}" PGDATABASE="${PGDATABASE:-modulis_profils}"
export TZ="${TZ:-Africa/Douala}"

log() { printf '%s [backup] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
die() { log "ERREUR : $*"; exit 1; }

keep_for() {
  case "$1" in
    daily) echo "$KEEP_DAILY" ;; weekly) echo "$KEEP_WEEKLY" ;; monthly) echo "$KEEP_MONTHLY" ;; manual) echo "$KEEP_MANUAL" ;;
    *) echo 0 ;;
  esac
}

encryption_enabled() { [[ -n "${BACKUP_PASSPHRASE:-}" ]]; }

wait_for_db() {
  local i
  for i in $(seq 1 60); do
    pg_isready -q && return 0
    sleep 2
  done
  die "PostgreSQL ($PGHOST:$PGPORT) ne répond pas"
}

# All backup folders, oldest first: <tier>/<stamp>
all_backups() {
  local tier
  for tier in "${TIERS[@]}"; do
    [[ -d "$BACKUP_ROOT/$tier" ]] || continue
    find "$BACKUP_ROOT/$tier" -mindepth 1 -maxdepth 1 -type d ! -name '.*' -printf "%f $tier/%f\n"
  done | sort | awk '{print $2}'
}

# Resolve "latest", a stamp (2026-11-13_023000) or a tier/stamp path to an absolute folder.
resolve_backup() {
  local ref="${1:-latest}" found=""
  if [[ "$ref" == "latest" ]]; then
    found="$(all_backups | tail -n 1)"
  elif [[ -d "$BACKUP_ROOT/$ref" ]]; then
    found="$ref"
  else
    found="$(all_backups | grep -E "/${ref}\$" | tail -n 1 || true)"
  fi
  [[ -n "$found" && -d "$BACKUP_ROOT/$found" ]] || die "sauvegarde introuvable : $ref (voir : make backup-list)"
  echo "$BACKUP_ROOT/$found"
}

# Decrypt (if needed) a backup file into a working dir; prints the plain file path.
plain_file() {
  local dir="$1" name="$2" work="$3"
  if [[ -f "$dir/$name.gpg" ]]; then
    encryption_enabled || die "$name est chiffré : définissez BACKUP_PASSPHRASE"
    gpg --batch --quiet --pinentry-mode loopback --passphrase "$BACKUP_PASSPHRASE" -o "$work/$name" -d "$dir/$name.gpg" \
      || die "déchiffrement impossible de $name (phrase secrète erronée ?)"
    echo "$work/$name"
  elif [[ -f "$dir/$name" ]]; then
    echo "$dir/$name"
  else
    echo ""
  fi
}

check_sums() {
  local dir="$1"
  [[ -f "$dir/SHA256SUMS" ]] || die "SHA256SUMS absent dans $dir"
  (cd "$dir" && sha256sum --quiet -c SHA256SUMS) || die "empreintes SHA-256 incorrectes dans $dir : fichier corrompu"
}
