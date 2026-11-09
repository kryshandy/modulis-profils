# ADR-0001 — Django 5.2 LTS + PostgreSQL

Statut : Proposée · 2026-11-09

## Contexte
La spécification recommande Laravel + MySQL parce que l'équipe connaît Laravel. Le porteur du projet privilégie Django
et veut apprendre à le maîtriser. Exigences : rendu serveur pour le SEO, back-office rapide, hébergement peu coûteux,
recherche par métier et ville, support à long terme.

## Décision
Django 5.2 (LTS, support de sécurité jusqu'en avril 2028) avec PostgreSQL 17.

## Alternatives
- **Laravel + MySQL** : aussi bon en SEO, mais ne correspond pas au choix du porteur.
- **Next.js + PostgreSQL** : SSR excellent, mais deux langages, hébergement Node, MVP plus long.
- **Django 6.x (non LTS)** : fonctions plus récentes (tâches intégrées, CSP), mais cycle de support court.
- **MySQL au lieu de PostgreSQL** : possible, mais `unaccent`, `pg_trgm` et la recherche plein texte de Django sont meilleurs sur PostgreSQL.

## Conséquences
- L'admin Django fournit une grande partie du back-office (lots de cartes, modération).
- Migration vers la LTS suivante à planifier en 2027.
- Il faut installer PostgreSQL en local sous Windows (pas de Docker sur le poste).
