# ADR-0011 — Sauvegardes de la base et des médias hors Docker

- Statut : accepté
- Date : 13 novembre 2026

## Contexte

La base PostgreSQL et les photos vivent dans des volumes Docker (`pgdata`, `media`). Ils survivent aux
reconstructions d'images, mais pas à `docker compose down -v`, à un nettoyage des volumes, à une
réinstallation de Docker ni à la perte du serveur. Le plan (§ 12, § 13) classe la perte de données
comme « fatale » et exige des sauvegardes quotidiennes, chiffrées, hors serveur, testées.

## Décision

Un service Compose `backup` (image `postgres:17-alpine` + gnupg + rclone) :

- écrit chaque nuit `pg_dump` (format personnalisé) + archive des médias dans un **dossier de l'hôte**
  monté en bind (`BACKUP_DIR`), jamais dans un volume Docker ;
- vérifie chaque fichier produit, calcule des empreintes SHA-256, chiffre en AES-256 si
  `BACKUP_PASSPHRASE` est défini (obligatoire en production via `BACKUP_REQUIRE_ENCRYPTION=1`) ;
- applique la rétention 7 quotidiennes / 4 hebdomadaires / 12 mensuelles / 10 manuelles ;
- synchronise le dossier vers un stockage hors site avec rclone si `RCLONE_REMOTE` est défini ;
- restaure chaque dimanche la dernière sauvegarde dans une base jetable (preuve de restaurabilité) ;
- expose son état à l'admin (fichier `last_success.json` lu en lecture seule par `web`) et à Docker
  (healthcheck : dernière réussite < 26 h).

`make up` sauvegarde avant de reconstruire ; `make restore` sauvegarde l'état courant avant de
restaurer.

## Alternatives écartées

- **restic** (prévu au plan) : déduplication et chiffrement excellents, mais un outil et un format de
  plus à maîtriser ; les volumes actuels (quelques Mo à quelques Go) n'en ont pas besoin. Il reste
  possible de pointer restic sur `BACKUP_DIR` plus tard.
- **Tâche Huey dans le worker** : la sauvegarde dépendrait du code applicatif et tomberait avec lui.
- **Volumes en bind mount directs** (`./data/pgdata`) : PostgreSQL sur un disque Windows monté dans
  WSL (drvfs) pose des problèmes de droits et de performance, et une copie à chaud des fichiers d'une
  base n'est pas une sauvegarde cohérente.
- **WAL / PITR (pgBackRest)** : restauration à la seconde, utile au-delà de quelques milliers de pages ;
  à reconsidérer quand la perte d'une journée de saisie deviendra inacceptable.

## Conséquences

- Perte maximale de données : 24 h (moins avec `make backup` avant toute opération risquée).
- La phrase de chiffrement et `.env` doivent être conservés hors du serveur.
- La version majeure de PostgreSQL de `backup` doit suivre celle de `db`.
