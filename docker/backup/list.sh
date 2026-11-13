#!/usr/bin/env bash
# List the backups (oldest first) with their size and content.
source /usr/local/bin/backup-lib.sh

printf '%-44s %8s  %s\n' "SAUVEGARDE" "TAILLE" "CONTENU"
count=0
while read -r rel; do
  [[ -n "$rel" ]] || continue
  dir="$BACKUP_ROOT/$rel"
  size=$(du -sh "$dir" | cut -f1)
  info="$(sed -n 's/.*"users": \([0-9]*\).*/\1/p' "$dir/manifest.json" 2>/dev/null) comptes, $(sed -n 's/.*"profiles": \([0-9]*\).*/\1/p' "$dir/manifest.json" 2>/dev/null) pages, $(sed -n 's/.*"media_files": \([0-9]*\).*/\1/p' "$dir/manifest.json" 2>/dev/null) médias"
  [[ -n "$(ls "$dir"/*.gpg 2>/dev/null)" ]] && info="$info, chiffrée"
  printf '%-44s %8s  %s\n' "$rel" "$size" "$info"
  count=$((count + 1))
done < <(all_backups)
echo
[[ -f "$BACKUP_ROOT/last_success.json" ]] && echo "Dernière réussite : $(cat "$BACKUP_ROOT/last_success.json")"
[[ -f "$BACKUP_ROOT/last_verify.json" ]] && echo "Dernière restauration test : $(cat "$BACKUP_ROOT/last_verify.json")"
echo "$count sauvegarde(s) dans $BACKUP_ROOT (dossier de l'hôte : ${BACKUP_HOST_DIR:-voir BACKUP_DIR})"
