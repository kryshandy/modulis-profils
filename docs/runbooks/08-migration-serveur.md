# Runbook 08 — Migration de serveur

**Objectif** : déplacer la production Modulis Profils vers un nouveau VPS avec un temps d'arrêt minimal et zéro perte de données.
**Référence** : [SAUVEGARDES.md](../SAUVEGARDES.md) · [01-restauration-sauvegarde.md](01-restauration-sauvegarde.md).

## 1. Préparer le nouveau serveur (sans couper l'ancien)
1. Installer Docker Engine et le plugin Docker Compose sur le nouveau VPS ; configurer le pare-feu (autoriser uniquement `22`, `80`, `443`).
2. Cloner le dépôt Modulis Profils et copier `.env` (vérifier la [checklist `.env` prod](README.md#checklist-env-de-production)), les certificats TLS (`docker/nginx/certs/` si utilisés) et la configuration `rclone` (`docker/backup/rclone/`).
3. Construire les images à l'avance pour éviter tout délai lors de la bascule :
   ```bash
   docker compose -f compose.prod.yaml build
   ```
4. Réduire le TTL DNS du domaine à **300 secondes** (5 minutes) au moins 24 h avant la migration (dans Cloudflare ou chez le registrar).

## 2. Sauvegarde finale sur l'ancien serveur (fenêtre de maintenance)
1. Activer le mode maintenance dans l'admin (`/gestion/` → Centre de contrôle) ou arrêter `web` et `worker` sur l'ancien serveur pour figer les écritures :
   ```bash
   docker compose -f compose.prod.yaml stop web worker
   ```
2. Lancer une sauvegarde manuelle complète et la vérifier :
   ```bash
   docker compose -f compose.prod.yaml run --rm backup backup.sh manual avant-migration
   docker compose -f compose.prod.yaml run --rm backup verify.sh latest
   ```
3. Transférer le dossier de sauvegarde vers le nouveau serveur (via `rclone` ou `rsync -avz`).

## 3. Restauration et démarrage sur le nouveau serveur
1. Démarrer `db` et `redis` :
   ```bash
   docker compose -f compose.prod.yaml up -d db redis
   ```
2. Restaurer la sauvegarde :
   ```bash
   docker compose -f compose.prod.yaml run --rm backup restore.sh latest --no-safety-backup --yes
   ```
3. Démarrer toute la pile :
   ```bash
   docker compose -f compose.prod.yaml up -d
   ```
4. Vérifier localement sur le nouveau serveur (`curl -fsS -H "Host: <domaine>" http://127.0.0.1/healthz`).

## 4. Bascule DNS et vérifications
1. Mettre à jour l'enregistrement DNS `A` (et `AAAA`) vers l'IP du nouveau VPS.
2. Surveiller les logs du nouveau serveur (`docker compose -f compose.prod.yaml logs -f nginx web worker`) pour confirmer l'arrivée du trafic.
3. Tester une page profil, `/c/<CODE>`, une image `/media/...`, et `/<ADMIN_URL>`.
4. Laisser l'ancien serveur éteint (sans détruire ses disques) pendant 7 jours en filet de sécurité avant de le résilier.
5. Remettre le TTL DNS à sa valeur normale et vérifier le passage de la prochaine sauvegarde nocturne sur le nouveau serveur.
