# État d'avancement des lots (MVP — Lots 0 à 9)

Référence produit : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 9 Feuille de route).

| Lot | Intitulé | Statut | Applications / Livrables en place dans le dépôt | Reste à faire / Remarques |
|---|---|---|---|---|
| **0** | Fondations | **Terminé** | `config/settings/{base,dev,test,prod}.py`, `apps/core`, Huey, Ruff, pytest, `Makefile`, Docker / WSL2 (ADR-0001, ADR-0002, ADR-0008). | — |
| **1** | Comptes & OTP | **Terminé** | `apps/accounts` : utilisateur personnalisé (téléphone E.164), OTP HMAC, limites de débit, WhatsApp Cloud API, SMS Firebase et backends SMS (ADR-0004, ADR-0009). | — |
| **2** | Profils & création auto | **Terminé** | `apps/profiles`, `apps/themes`, `apps/dashboard`, `apps/blocks` : `SlugRegistry`, `get_or_create_profile`, galerie WebP, espace pro `/espace/` HTMX, 13 thèmes (6 directions artistiques), constructeur par blocs encadrés (ADR-0012). | — |
| **3** | Page publique & SEO | **Terminé** | `apps/public`, `apps/seo` : rendu 100 % serveur, balises meta, JSON-LD (dont `FAQPage`), image OG, canonical, `robots.txt`, sitemaps, score de complétude, détection des bios dupliquées, 404/410, mini-annuaire ville et métier×ville, notifications `kliz` (ADR-0003, ADR-0007). | — |
| **4** | vCard & QR | **Terminé** | `apps/public/vcard.py` et vues associées : vCard 3.0 compatible iOS/Android, QR PNG/SVG, partage WhatsApp. | — |
| **5** | Cartes NFC | **Terminé** | `apps/cards` : lots, génération de codes, codes d'activation secrets, export imprimeur, `/c/<code>` en 302 + `noindex`, activation, liaison et remplacement (ADR-0005). | — |
| **6** | Statistiques | **Terminé** | `apps/analytics` : collecte d'événements, filtrage des robots, agrégats quotidiens, tableau de bord dans l'espace pro. | — |
| **7** | Back-office & modération | **Terminé** | `apps/moderation`, `apps/platform`, `apps/security` : admin Django personnalisé, centre de contrôle des fonctionnalités, gestion des signalements, suspension, badge vérifié, 2FA TOTP obligatoire pour l'équipe (ADR-0010). | — |
| **8** | Offres & paiement | **En cours** | `apps/billing` : modèles `Plan`, `PlanPrice`, `Subscription`, `Payment`, gestion des droits (`entitlements`, `grant_plan`, `expire_subscriptions`), tâche Huey et admin. | Finalisation du fournisseur Mobile Money, de l'interface de facturation dans `/espace/` et des tests bout en bout. |
| **9** | Durcissement & préproduction | **En cours** | `apps/legal` (CGU, confidentialité, mentions légales), `apps/security`, sauvegardes hors Docker (`docker/backup`, `docs/SAUVEGARDES.md`, ADR-0011), `docs/SECURITE-ADMIN.md`, `docs/LANCEMENT.md`. | Compléter les runbooks d'exploitation et finaliser la configuration serveur de préproduction / production. |

