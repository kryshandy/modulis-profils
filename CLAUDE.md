# Règles de travail — Modulis Profils

Ce fichier est lu par Claude et par ses sous-agents à chaque session. La référence produit est `docs/00-PLAN-COMPLET.md`.

## Langue
Code, noms et commentaires de code en anglais ; interface (avec gettext, en tutoyant), documentation et commits en français.

## Pile
Python 3.13 (Docker) / 3.14 (venv WSL) · Django 5.2 LTS · PostgreSQL 17 · Redis 7 · Huey · HTMX · pytest · kliz (indexation).
Aucun framework JS. Aucune ressource externe (CDN, polices) sur les pages publiques.

## Commandes (toujours dans WSL Ubuntu, à la racine du projet)
- `make test` : tests rapides (venv, SQLite en mémoire) · `make check` : lint + checks Django + migrations + tests + couverture ≥ 80 %
- `make up` / `make logs` / `make down` : environnement Docker (web, worker, PostgreSQL, Redis). Les SMS de dev s'affichent dans `make logs`.
- `make dtest` : tests sur PostgreSQL dans Docker · `make fmt` : formatage Ruff
- Depuis PowerShell : `wsl -e bash -lc 'cd /mnt/c/Users/HP/Desktop/modulis-profils && make test'` (guillemets simples).

## Règles non négociables
- Dépôt distant : `origin` = https://github.com/kryshandy/modulis-profils (décision du porteur, 11 nov. 2026). Seule la session principale pousse, après `make check` vert ; **jamais de push forcé** ni de réécriture d'historique. Pas d'Actions GitHub ni de hook `pre-commit` téléchargé : les vérifications restent locales.
- Données : jamais de `docker compose down -v` ni de suppression de volume sans `make backup` + `make backup-verify` récents (docs/SAUVEGARDES.md, ADR-0011). Toute nouvelle collecte ou conservation de données personnelles se reflète dans `apps/legal/templates/legal/confidentialite.html` ; tout changement important des CGU augmente `LEGAL_VERSION`.
- Rendu serveur pour toute page publique ; aucun contenu indexable injecté en JavaScript ; CSP stricte, donc aucun script ni style en ligne.
- Une application ne modifie pas les modèles d'une autre : elle passe par le `services.py` de celle-ci.
- Toute création de profil passe par `profiles.services.create_profile` / `get_or_create_profile` (anti-doublon par téléphone E.164).
- Unicité des slugs : uniquement via `SlugRegistry`. `/c/<code>` répond en **302** + `noindex` ; les **301** sont réservées aux anciens slugs ; profil effacé = **410**.
- OTP par **WhatsApp (API Cloud de Meta)**, **SMS via Firebase** ou passerelle SMS (ADR-0009), chaque canal activable dans le centre de contrôle ; nos codes stockés en HMAC. Toute fonction activable se lit via `apps.platform.services.feature()`. Activation de carte : vérifier le code d'activation **avant** d'envoyer un OTP.
- `ATOMIC_REQUESTS=True` : une vue doit **attraper** les exceptions métier (`OTPError`, `CardError`, `ValidationError`) et réafficher le formulaire. Une exception qui remonte annule les compteurs d'essais (faille de force brute). De même, un service ne lève jamais d'exception à l'intérieur de son propre `transaction.atomic()` après avoir incrémenté un compteur.
- JSON-LD échappé (`<`, `>`, `&`) ; liens utilisateurs : `https:`, `tel:`, `mailto:`, `wa.me` uniquement, avec `rel="ugc nofollow"`.
- Chaque vue de `/espace/` filtre par `request.user` (pas d'IDOR).
- Secrets uniquement dans `.env` ; jamais de vraies données personnelles dans les fixtures.
- Toute décision qui change le plan = un ADR dans `docs/adr/` + mise à jour du plan.

## Équipe d'agents (`.claude/agents/`)
`backend-django`, `frontend-ux`, `seo-expert`, `devops-docker` (écriture) · `code-reviewer`, `security-auditor` (lecture seule).
- La session principale planifie, délègue chaque tâche avec un **périmètre de fichiers exclusif**, relit tout, lance `make check` et **seule elle commite**.
- Les agents qui travaillent en parallèle ne touchent pas aux mêmes fichiers et ne formatent que leurs propres fichiers.
- Fin de lot : revue `code-reviewer` + `security-auditor` (+ `seo-expert` si des pages publiques ont changé), corrections, puis commit.

## Commits
Conventional Commits en français : `feat(cards): activation par code secret`, `fix(accounts): …`, `docs: …`, `test: …`.
