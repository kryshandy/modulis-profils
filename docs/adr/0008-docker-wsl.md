# ADR-0008 — Développement dans Docker sous WSL2 Ubuntu

Statut : Acceptée · 2026-11-09 (remplace la partie « Windows natif sans Docker » de l'ADR-0001)

## Contexte
Le porteur dispose de WSL2 Ubuntu et veut un environnement propre et reproductible, identique à la production.

## Décision
- Docker Engine installé dans Ubuntu WSL (`scripts/wsl/install-docker.sh`, dépôt officiel de Docker).
- `compose.yaml` (dev) : `web` (runserver), `worker` (Huey), `db` (PostgreSQL 17), `redis` (Redis 7), avec des healthchecks.
- Image `docker/django/Dockerfile` multi-étapes : `dev` (outils de test, UID 1000 pour le montage) et `prod` (Gunicorn, utilisateur système non root, collectstatic, healthcheck).
- Un venv WSL (`~/.venvs/modulis-profils`) reste disponible pour lancer les tests rapidement (SQLite en mémoire) et pour les hooks git. `make dtest` lance les mêmes tests sur PostgreSQL dans Docker.
- Toutes les commandes passent par le `Makefile`, exécuté dans WSL. Le `check.ps1` prévu dans le plan v1.1 est abandonné.

## Conséquences
Le projet reste sur le Bureau Windows (`/mnt/c/...`). Les accès disque y sont plus lents que dans le système de fichiers
Linux, mais c'est acceptable pour ce projet. Si cela gêne, déplacer le dépôt dans `~/projets/` sous WSL.
