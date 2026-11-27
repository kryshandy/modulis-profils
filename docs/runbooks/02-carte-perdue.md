# Runbook 02 — Remplacer une carte NFC perdue ou volée

**Objectif** : empêcher qu'un tiers utilise une carte perdue ou volée tout en conservant le profil, le slug et les statistiques du professionnel.

## Contexte technique
- Les URLs `/c/<CODE>` répondent en **302** (`noindex`), jamais en 301 : dès qu'une carte est désactivée, les scans suivants cessent immédiatement de rediriger vers le profil.
- Un profil peut être lié à plusieurs cartes ; la perte d'une carte n'affecte ni le compte ni la page publique.

## 1. Vérifier l'identité du demandeur
Avant toute action côté support :
- Confirmer le numéro de téléphone E.164 du compte (`+237...`).
- Si le professionnel a encore accès à son `/espace/`, lui indiquer qu'il peut aussi signaler/gérer ses cartes depuis son espace, ou effectuer l'opération depuis l'administration si son téléphone a été perdu en même temps.

## 2. Désactiver la carte perdue dans l'administration
1. Se connecter à `/<ADMIN_URL>` (mot de passe + 2FA TOTP).
2. Aller dans **Cartes (`cards`) → Cartes**.
3. Rechercher par `public_code` (7 caractères) ou par téléphone / slug du profil.
4. Passer le statut de la carte à **Désactivée** (`disabled`), renseigner `disabled_at` et `disabled_reason = perdue` (ou `remplacée` / `volée`).
5. Enregistrer.

## 3. Associer une carte de remplacement (si applicable)
- **Cas A — Le pro a déjà une nouvelle carte en main** : il scanne `/c/<NOUVEAU_CODE>`, saisit le code d'activation à gratter, s'authentifie par OTP avec son numéro habituel et sélectionne « Associer cette carte à mon profil ».
- **Cas B — Expédition d'une nouvelle carte** : expédier une carte vierge (`stock`/`vendue`) sans pré-activation ; le pro l'activera à réception pour conserver la protection du code d'activation secret.

## 4. Vérification
- Ouvrir `https://<domaine>/c/<ANCIEN_CODE>` : la page doit afficher « Carte désactivée » (aucune redirection vers le profil).
- Vérifier que `https://<domaine>/<slug>` reste accessible et inchangé.
