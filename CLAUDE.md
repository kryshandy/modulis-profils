# Règles de travail — Modulis Profils

Ce fichier est lu par Claude et par ses sous-agents à chaque session. La référence produit est `docs/00-PLAN-COMPLET.md`.

## Langue
Code, noms de variables et commits en anglais ; interface, documentation et explications en français.

## Pile
Python 3.13 · Django 5.2 LTS · PostgreSQL 17 · Huey · HTMX · pytest. Aucun framework JS sur les pages publiques.

## Règles non négociables
- **Aucune interaction avec GitHub** (ni remote, ni push, ni `pre-commit` qui télécharge depuis GitHub). Git local seulement.
- Rendu serveur pour toute page publique ; aucun contenu indexable injecté en JavaScript.
- Une application ne touche pas aux modèles d'une autre directement : passer par son `services.py`.
- Toute création de profil passe par `profiles.services.get_or_create_profile` (anti-doublon par téléphone E.164).
- `/c/<code>` répond en **302** et `noindex`. Les **301** servent uniquement aux anciens slugs.
- Le format d'URL des cartes `https://DOMAINE/c/XXXXXXX` est figé à vie.
- Secrets dans `.env` uniquement ; jamais de vraies données personnelles dans les fixtures.
- Chaque changement est accompagné de tests ; `scripts/check.ps1` doit passer avant un commit.
- Unicité des slugs : uniquement via la table `SlugRegistry`.
- Activation de carte : vérifier le code d'activation **avant** d'envoyer un OTP.
- JSON-LD construit à partir de données utilisateur : toujours échappé (`<`, `>`, `&`).
- Liens saisis par les utilisateurs : schémas `https:`, `tel:`, `mailto:` et `wa.me` uniquement, avec `rel="ugc nofollow"` sur les profils gratuits.
- Une décision qui change le plan = un ADR dans `docs/adr/` + mise à jour du plan.

## Supervision
- La session principale planifie, délègue aux sous-agents, **relit tout** et seule elle commite.
- Les sous-agents travaillent sur une tâche précise tirée de la fiche de lot, avec ses critères d'acceptation.
- Fusion dans `main` uniquement après revue et accord de l'utilisateur.

## Commits
Conventional Commits : `feat(scope): …`, `fix(scope): …`, `docs: …`, `test: …`, `refactor: …`, `chore: …`.
