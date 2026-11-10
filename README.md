# Modulis Profils — plateforme de profils pros & cartes NFC

Chaque professionnel obtient une page gratuite à une **adresse unique** (`domaine/son-nom`), **optimisée
automatiquement pour Google**, accessible par un QR code ou une **carte NFC permanente** (`domaine/c/CODE`).
La page est **créée automatiquement** (inscription, premier scan d'une carte ou agent terrain) et le pro la gère depuis
un espace discret (`/espace/`), avec un onboarding et une visite guidée.

Projet **séparé** du site vitrine Modulis (autre dossier, dépôt git, domaine). Versionnage **git local uniquement**.

## Démarrer (dans WSL Ubuntu)

```bash
cd /mnt/c/Users/HP/Desktop/modulis-profils
cp .env.example .env          # puis remplir les secrets (déjà fait sur ce poste)
make up                       # web + worker + PostgreSQL + Redis dans Docker
make dmanage cmd=seed_demo    # profils fictifs, lot de cartes, compte admin
make logs                     # les codes SMS de dev s'affichent ici
```

| Adresse | Rôle |
|---|---|
| http://localhost:8000/ | accueil de la plateforme |
| http://localhost:8000/espace/ | espace pro (connexion par code SMS) |
| http://localhost:8000/gestion/ | administration (utilisateurs, pages, cartes, offres, modération, KPI) |
| http://localhost:8000/c/CODE | scan d'une carte / activation |

Tests rapides sans Docker : `make test` · vérification complète avant commit : `make check` · sur PostgreSQL : `make dtest`.
`make help` liste toutes les commandes.

## Arborescence

```
modulis-profils/
├── .claude/
│   ├── agents/              équipe d'agents : backend-django, frontend-ux, seo-expert, devops-docker,
│   │                        code-reviewer, security-auditor
│   └── settings.json        interdits : git push, gh, lecture de .env et des exports de cartes
├── .githooks/pre-commit     Ruff sur les fichiers indexés (hook local, sans GitHub)
├── apps/
│   ├── core/                pays, villes, métiers (données Cameroun), utilitaires IP, healthz,
│   │                        KPI de l'admin, commande seed_demo
│   ├── accounts/            utilisateur = téléphone E.164, OTP SMS (HMAC, limites), backends SMS
│   ├── profiles/            profils, SlugRegistry, création automatique, complétude, indexabilité
│   ├── cards/               lots, codes, scan /c/, assistant d'activation, export imprimeur
│   ├── public/              accueil, page profil, pages ville et métier×ville, vCard, QR, image OG
│   ├── seo/                 meta, JSON-LD, sitemaps, robots.txt, clé IndexNow, kliz (file + tâches)
│   ├── dashboard/           espace pro : connexion, onboarding, éditeur HTMX, partage, cartes,
│   │                        statistiques, paramètres, aide, visite guidée
│   ├── analytics/           pixel de visite, balise de clic, filtrage des robots, agrégats journaliers
│   ├── moderation/          signalements et actions de modération
│   └── billing/             offres, prix par pays, abonnements, droits, rappels d'expiration
├── config/                  settings/{base,dev,test,prod}.py, urls.py (le slug de profil en dernier)
├── docker/django/           Dockerfile multi-étapes (dev/prod), entrypoint
├── compose.yaml             web, worker (Huey), db (PostgreSQL 17), redis (Redis 7)
├── docs/
│   ├── 00-PLAN-COMPLET.md   la référence produit et technique
│   ├── adr/                 décisions d'architecture 0001 à 0008
│   ├── etudes/kliz.md       étude du paquet kliz
│   ├── lots/                fiches de lots
│   └── revues/              comptes rendus de revue
├── requirements/            *.in (intentions) → *.txt (versions figées)
├── scripts/wsl/             installation de Docker, sauvegarde du dépôt (git bundle)
├── static/                  css/app.css (espace pro), css/profile.css (pages publiques), js/, img/
├── templates/               base, dashboard, admin, 404/410
├── tests/factories.py       factories partagées (données fictives)
├── conftest.py · pyproject.toml (Ruff, pytest, coverage) · Makefile · manage.py
```

## Documentation

- [docs/00-PLAN-COMPLET.md](docs/00-PLAN-COMPLET.md) : architecture, URL, SEO, parcours, lots, maintenance, risques
- [docs/adr/](docs/adr/) : décisions (Django, Huey, 302/301, téléphone, code d'activation, multi-pays, kliz, Docker)
- [docs/etudes/kliz.md](docs/etudes/kliz.md) : ce que vaut kliz pour nous et comment on va plus loin
- [CLAUDE.md](CLAUDE.md) : règles de travail des agents IA
