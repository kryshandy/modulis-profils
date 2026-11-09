#!/usr/bin/env bash
# Sauvegarde du dépôt git local (sans GitHub) : un bundle horodaté vers un support externe.
# Usage : bash scripts/wsl/backup-repo.sh /mnt/d/backups/modulis-profils
set -euo pipefail
DEST="${1:-$HOME/backups/modulis-profils}"
mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
git bundle create "$DEST/modulis-profils-$STAMP.bundle" --all
git bundle verify "$DEST/modulis-profils-$STAMP.bundle" >/dev/null
# Keep the 30 most recent bundles.
ls -1t "$DEST"/modulis-profils-*.bundle | tail -n +31 | xargs -r rm --
echo "Bundle OK : $DEST/modulis-profils-$STAMP.bundle"
