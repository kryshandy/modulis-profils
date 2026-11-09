# ADR-0002 — Huey pour les tâches de fond

Statut : Proposée · 2026-11-09

## Contexte
Il faut exécuter hors requête : génération des sitemaps et des images OG, envoi des SMS, agrégation des statistiques,
rapprochement des paiements, rappels d'abonnement. Le développement se fait sous Windows, sans Docker.

## Décision
Huey : stockage SQLite en développement, Redis en production. Tâches périodiques via `@periodic_task`.

## Alternatives
- **Celery + Redis** : standard du marché, mais ne fonctionne plus officiellement sous Windows et demande Redis dès le dev.
- **django-q2** : correct, communauté plus petite.
- **Framework de tâches intégré à Django 6** : nécessite Django 6 et un backend tiers encore jeune.

## Conséquences
Démarrage simple (`python manage.py run_huey`). Si la charge l'exige un jour, passer à Celery est localisé :
les tâches sont appelées depuis les `services.py`.
