# Modulis Profils — plateforme de profils pros & cartes NFC

Chaque professionnel obtient une page gratuite à une adresse unique (`domaine/son-nom`), optimisée pour Google,
accessible par un QR code ou une carte NFC permanente (`domaine/c/CODE`).

Projet **séparé** du site vitrine Modulis : autre dossier, autre dépôt git, autre domaine.

## Où lire quoi

| Document | Contenu |
|---|---|
| [docs/00-PLAN-COMPLET.md](docs/00-PLAN-COMPLET.md) | **La référence** : architecture, URL, SEO, parcours, lots, méthode, maintenance, risques, questions ouvertes |
| [docs/adr/](docs/adr/) | Décisions d'architecture (une par fichier) |
| [docs/lots/](docs/lots/) | Fiche de chaque lot de développement |
| [CLAUDE.md](CLAUDE.md) | Règles de travail pour les agents de codage |

## État

Phase de conception. Le code commence au **lot 0** (voir `docs/lots/LOT-00-fondations.md`).

## Versionnage

Git **local uniquement** (pas de GitHub). Branche `main` stable, une branche `feature/lot-xx-…` par lot,
commits au format Conventional Commits, tags `v0.x.0`.
