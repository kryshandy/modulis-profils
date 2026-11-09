# Revue du plan v1.0 — 9 novembre 2026

Relecteur : sous-agent architecte (Django + SEO technique). Superviseur : session principale.
Méthode : chaque remarque a été vérifiée par le superviseur avant intégration.

## Bloquants (tous intégrés au plan v1.1)
| # | Remarque | Intégration |
|---|---|---|
| 1 | Pas de maillage interne avant la V2 → profils orphelins | Mini-annuaire au lot 3 (§ 6.9, A14) |
| 2 | Score de 70 atteignable sans aucun texte propre | Bio obligatoire, 60 mots minimum, détection des bios dupliquées (§ 6.6) |
| 3 | Domaine `.cm` figé sur les cartes vs multi-pays | ADR du domaine des cartes avant le lot 5 (A13, ADR-0006) |
| 4 | Puces NFC réécrivables | Verrouillage obligatoire (A15, § 4.3, ADR-0005) |
| 5 | OTP envoyé avant le code d'activation → fraude aux SMS | Ordre inversé + protections anti-SMS-pumping (§ 5.2, § 7) |
| 6 | Unicité des slugs répartie sur plusieurs tables | Table unique `SlugRegistry` (§ 3.3) |

## Importants (intégrés)
`robots.txt` sans blocage des paramètres et préproduction protégée par mot de passe · 404/410 pour les profils privés,
suspendus ou supprimés · cache CDN (pixel de comptage, pas de CSRF dans le cache, `CF-Connecting-IP`) · numéros recyclés ·
User 1–N Profile et `Card.owner_org` · échappement du JSON-LD et liens `ugc nofollow` · jeton de consentement pour les
agents terrain · bilinguisme fr/en · `django-csp`, `django-otp`, Alpine en version CSP · Huey au lot 0 avec battement de
cœur · sauvegarde du dépôt par `git bundle`, hooks adaptés à Windows, `check.ps1` au lieu de `make`.

## Mineurs (intégrés)
Alphabet des codes = 30 symboles (et non 31) ; codes insensibles à la casse · blocage d'activation par (carte, IP) · OTP
en HMAC · versions Python et PostgreSQL précisées · `content_updated_at` pour `lastmod` · `X-Robots-Tag` sur vCard, QR et
image OG · politique de slash final · partitionnement des événements reporté · compléments de maintenance.

## À vérifier plus tard (incertain)
- Règle de Google sur les avis « auto-promotionnels » → avant la V2.
- Limite de poids de l'image OG pour l'aperçu WhatsApp (~300 Ko) → à tester au lot 3.
- Support de Python 3.14 par Django 5.2.x et par toutes les dépendances → avant toute montée de version.
