# Runbook 01 — Restauration d'une sauvegarde

**Objectif** : restaurer la base PostgreSQL et/ou les médias depuis une sauvegarde chiffrée (ou exécuter le test mensuel de restauration).
**Référence** : [SAUVEGARDES.md](../SAUVEGARDES.md) · ADR-0011.

## Prérequis
- Accès SSH au serveur de production.
- `BACKUP_PASSPHRASE` disponible (dans `.env` ou le gestionnaire de mots de passe de l'équipe).
- Ne **jamais** exécuter `docker compose down -v` avant d'avoir vérifié la sauvegarde.

## 1. Lister et vérifier les sauvegardes disponibles

```bash
docker compose -f compose.prod.yaml run --rm backup list.sh
docker compose -f compose.prod.yaml run --rm backup verify.sh latest
```

Pour une sauvegarde précise (ex. `2026-11-14_023000`) :

```bash
docker compose -f compose.prod.yaml run --rm backup verify.sh 2026-11-14_023000
```

Le script `verify.sh` contrôle les empreintes `SHA256SUMS`, déchiffre avec GPG et restaure dans une base jetable. **Ne jamais restaurer en production une sauvegarde qui échoue à `verify.sh`.**

## 2. Restaurer base + médias (avec coupure brève)

`restore.sh` crée automatiquement une sauvegarde de sécurité (`manual/…_avant-restauration`) avant d'écraser les données.

```bash
# 1. Arrêter web et worker pour figer les écritures
docker compose -f compose.prod.yaml stop web worker

# 2. Restaurer la dernière sauvegarde (ou un nom précis)
docker compose -f compose.prod.yaml run --rm backup restore.sh latest --yes

# 3. Redémarrer web et worker
docker compose -f compose.prod.yaml start web worker
```

Options ciblées :
- Base seule : `restore.sh <nom> --db-only --yes`
- Médias seuls : `restore.sh <nom> --media-only --yes`

## 3. Reprise après sinistre (serveur neuf ou volumes perdus)

1. Installer Docker Engine + Compose, cloner le dépôt et restaurer `.env` (hors serveur).
2. Rapatrier le dossier de sauvegardes dans `BACKUP_DIR` (disque externe ou `rclone copy <remote> <BACKUP_DIR>`).
3. Démarrer uniquement la base et Redis :
   ```bash
   docker compose -f compose.prod.yaml up -d db redis
   ```
4. Restaurer sans sauvegarde de sécurité (base vierge) :
   ```bash
   docker compose -f compose.prod.yaml run --rm backup restore.sh latest --no-safety-backup --yes
   ```
5. Démarrer toute la pile :
   ```bash
   docker compose -f compose.prod.yaml up -d --build
   ```

## 4. Vérifications post-restauration

- `curl -fsS http://127.0.0.1/nginx-healthz` et `docker compose -f compose.prod.yaml exec web curl -fsS http://127.0.0.1:8000/healthz` retournent `200`.
- Ouvrir une page profil publique, une image `/media/...` et `/<ADMIN_URL>` (vérifier le bandeau « État de la plateforme »).
- Vérifier `docker compose -f compose.prod.yaml logs --tail=50 web worker`.
