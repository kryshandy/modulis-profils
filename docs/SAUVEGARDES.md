# Sauvegardes de la base et des médias (hors Docker)

> Objectif : ne **jamais** perdre les comptes, les pages et les photos des pros, ni lors d'une
> reconstruction (`make up`, `docker compose build`), ni après un `docker compose down -v`, un
> `docker volume prune`, une réinstallation de Docker ou la panne du serveur.

## Le principe en une image

```
 PostgreSQL (volume pgdata) ──pg_dump──┐
                                       ├─► service « backup » ─► BACKUP_DIR (dossier de l'HÔTE, hors Docker)
 Photos   (volume media)  ──tar.gz────┘                              │
                                                                     └─► copie hors site (rclone, facultatif)
```

- Les volumes Docker (`pgdata`, `media`) gardent les données **en service** ; ils survivent déjà à
  `make up` / `docker compose build`. Mais ils disparaissent avec `docker compose down -v`, un
  nettoyage des volumes ou la perte de la machine.
- Le service `backup` écrit donc chaque nuit une copie complète **dans un dossier de l'hôte**
  (`BACKUP_DIR`, par défaut `./backups`, à côté du projet, sur le disque Windows en développement).
  Ce dossier n'appartient pas à Docker et n'est pas versionné par Git.
- En production, `BACKUP_DIR` doit viser **un autre disque** que celui des volumes, **et** une copie
  hors site (rclone vers un stockage objet) doit être active : un serveur qui brûle emporte son disque.

## Ce que contient une sauvegarde

Un dossier par sauvegarde, par exemple `backups/daily/2026-11-14_023000/` :

| Fichier | Contenu |
|---|---|
| `db.dump` (ou `db.dump.gpg`) | toute la base PostgreSQL, format `pg_dump` personnalisé, compressé |
| `media.tar.gz` (ou `.gpg`) | toutes les photos (originaux et variantes WebP) |
| `manifest.json` | date, versions PostgreSQL, nombre de tables, de comptes, de pages, de fichiers |
| `SHA256SUMS` | empreintes : toute corruption est détectée avant une restauration |

À chaque sauvegarde, le dump est relu (`pg_restore --list`) et l'archive testée (`tar -t`).

## Calendrier et rétention

| Quand | Quoi | Conservées |
|---|---|---|
| Chaque nuit à `BACKUP_TIME` (02:30, heure de Douala) | `daily/` | 7 |
| Le dimanche | copie dans `weekly/` + **restauration test complète** | 4 |
| Le 1er du mois | copie dans `monthly/` | 12 |
| `make backup`, avant `make up`, avant `make restore` | `manual/` | 10 |
| Au démarrage, si la dernière a plus de 26 h | sauvegarde de rattrapage | — |

Une donnée supprimée par un pro disparaît donc de toutes les sauvegardes en 12 mois au plus
(c'est ce qu'annonce la politique de confidentialité, § 7).

## Les commandes (depuis WSL, à la racine du projet)

```bash
make backup                                  # sauvegarde immédiate (label=avant-migration pour la nommer)
make backup-list                             # liste, tailles, contenu, dernière réussite
make backup-verify                           # restauration test de la dernière dans une base jetable
make backup-verify name=2026-11-14_023000    # … d'une sauvegarde précise
make restore name=latest                     # restaure base + médias (web et worker arrêtés pendant)
make restore name=2026-11-14_023000 only=--db-only      # la base seulement
make restore name=2026-11-14_023000 only=--media-only   # les photos seulement
make up                                      # sauvegarde automatique AVANT de reconstruire
docker compose logs backup                   # journal du planificateur
```

`make restore` prend d'abord une **sauvegarde de sécurité** de l'état actuel
(`manual/…_avant-restauration`) : une restauration se défait en restaurant celle-ci.

## Reprise après sinistre (serveur ou Docker perdu)

1. Réinstaller Docker, récupérer le code (`git clone` du dépôt) et le fichier `.env` (gardé hors serveur).
2. Remettre le dossier de sauvegardes en place (disque, ou `rclone copy <remote> ./backups`).
3. `docker compose up -d db redis` : base vide, volumes neufs.
4. `docker compose run --rm backup restore.sh latest --no-safety-backup --yes`
5. `make up` puis vérifier `http://localhost:8000/healthz`, une page pro et une photo.

Ce scénario a été joué le 13 novembre 2026 avec des volumes vierges (projet Docker séparé) :
12 comptes, 9 pages et 253 photos restaurés, pages et photos servies normalement.

## Chiffrement (obligatoire en production)

Les sauvegardes contiennent des données personnelles (numéros, noms, photos).

```dotenv
BACKUP_PASSPHRASE=une-longue-phrase-secrete-aleatoire
BACKUP_REQUIRE_ENCRYPTION=1   # refuse de produire une sauvegarde en clair
```

- Chiffrement symétrique AES-256 (gpg) de `db.dump` et `media.tar.gz`.
- **La phrase secrète doit être conservée hors du serveur** (gestionnaire de mots de passe de
  l'équipe). Sans elle, aucune sauvegarde chiffrée n'est restaurable ; une phrase erronée est refusée
  proprement.
- Changer de phrase : les nouvelles sauvegardes utilisent la nouvelle ; garder l'ancienne tant que
  des sauvegardes chiffrées avec elle sont conservées (12 mois au plus).

## Copie hors site (fortement recommandée en production)

1. Créer un `rclone.conf` (`rclone config` sur un poste) pour un stockage objet (Backblaze B2,
   Wasabi, S3, Google Drive…), le placer dans `docker/backup/rclone/` (ignoré par Git) ou indiquer
   son dossier dans `RCLONE_CONFIG_DIR`.
2. `.env` : `RCLONE_REMOTE=b2:modulis-sauvegardes` (nom du remote + chemin).
3. Après chaque sauvegarde, le dossier est synchronisé (`rclone sync`, rotation comprise). Un échec
   n'annule pas la sauvegarde locale et s'affiche dans l'admin (« Copie hors site en échec »).
4. Activer le chiffrement : le prestataire ne voit alors que des fichiers chiffrés.

## Surveillance

- **Admin** (`/gestion/`, bandeau « État de la plateforme ») : « Sauvegarde : il y a 3 h · chiffrée ·
  hors site », ou en rouge « Sauvegarde en retard » / « Aucune sauvegarde trouvée ».
- **Docker** : le service `backup` est `unhealthy` si la dernière sauvegarde a plus de
  `BACKUP_MAX_AGE_HOURS` (26 h) ; brancher Uptime Kuma ou l'alerte de l'hébergeur dessus.
- `backups/last_success.json` et `backups/last_verify.json` : dernière réussite, dernière
  restauration test.

## Règles à ne jamais enfreindre

- Ne jamais lancer `docker compose down -v` ni `docker volume rm/prune` sans une sauvegarde de moins
  d'une heure (`make backup`) **vérifiée** (`make backup-verify`).
- Une sauvegarde n'existe que si sa restauration a été testée : le test du dimanche est automatique ;
  faire en plus un `make backup-verify` à la main une fois par mois et après toute mise à jour de
  PostgreSQL.
- Le service `backup` utilise la même version majeure de PostgreSQL que `db` (17) : les deux images
  se mettent à jour ensemble.
- Un dossier de sauvegardes ne se publie jamais (Git, partage, messagerie).

## Fichiers

| Fichier | Rôle |
|---|---|
| `docker/backup/Dockerfile` | image `postgres:17-alpine` + gnupg + rclone |
| `docker/backup/entrypoint.sh` | planificateur (heure fixe, rattrapage, test du dimanche) |
| `docker/backup/backup.sh` | une sauvegarde : dump, archive, empreintes, chiffrement, rotation, hors site |
| `docker/backup/restore.sh` | restauration (sauvegarde de sécurité d'abord) |
| `docker/backup/verify.sh` | restauration test dans une base jetable |
| `docker/backup/list.sh` | inventaire |
| `docker/backup/healthcheck.sh` | santé Docker (âge de la dernière sauvegarde) |
| `apps/platform/backups.py` | état affiché dans l'admin |
