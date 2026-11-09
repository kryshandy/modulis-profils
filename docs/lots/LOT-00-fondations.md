# Lot 0 — Fondations

Statut : à valider · Branche : `feature/lot-00-fondations`

## Objectif
Un projet Django vide mais professionnel : il démarre, il est testé, il est vérifié automatiquement à chaque commit.

## Tâches
1. Installer Python 3.13 (`winget install Python.Python.3.13`) et PostgreSQL 17 (`winget install PostgreSQL.PostgreSQL.17`), puis désactiver l'alias Python du Microsoft Store.
2. Créer le venv `.venv`, `requirements/base.txt`, `dev.txt` et `prod.txt` avec des versions épinglées.
3. `django-admin startproject config .` ; réglages découpés `config/settings/{base,dev,test,prod}.py` ; `django-environ` ; `.env.example`.
4. Créer la base `modulis_profils` et l'utilisateur PostgreSQL dédié ; activer les extensions `unaccent` et `pg_trgm` par migration.
5. Applications `apps/core` (Country, City, Trade + données initiales Cameroun) et `apps/accounts` (modèle User personnalisé **avant la première migration**).
6. Ruff (`pyproject.toml`), pytest + pytest-django + factory_boy + coverage.
7. Huey (SQLite en dev, `immediate=True` en test) + une tâche d'exemple testée.
8. `scripts/check.ps1` : ruff, `manage.py check`, `makemigrations --check`, pytest avec couverture (vérifier la politique d'exécution PowerShell).
9. Hooks git locaux `.githooks/pre-commit` (Ruff + tests rapides) et `pre-merge-commit` (suite complète), écrits pour le `sh` de Git Bash et appelant `.venv/Scripts/python.exe` ; `git config core.hooksPath .githooks`.
10. `scripts/backup-repo.ps1` : `git bundle create` horodaté vers un disque externe, plus la tâche planifiée Windows associée.
11. Page d'accueil provisoire + `robots.txt` piloté par un réglage (`ROBOTS_ALLOW`) ; un test garantit qu'en réglages prod il n'est pas `Disallow: /`.
12. Note pédagogique : projet vs application, réglages, migrations, modèle User personnalisé, venv, hooks git.

## Critères d'acceptation
- `scripts/check.ps1` passe et reste vert.
- `python manage.py runserver` affiche la page d'accueil.
- Les données Cameroun (villes principales, ~30 métiers avec leur type schema.org) sont chargées par migration.
- Aucun secret dans git (`git grep -i secret` ne renvoie que `.env.example`).

## Agents
Plan → 1 développeur (tâches séquentielles) → relecteur → validation par vous → fusion + tag `v0.1.0`.
