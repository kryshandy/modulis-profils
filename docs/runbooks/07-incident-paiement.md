# Runbook 07 — Incident ou remboursement de paiement

**Objectif** : résoudre un paiement Mobile Money débité sans activation de l'abonnement, un double débit ou une demande de remboursement.
**Référence** : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 5.3, § 8).

## Règle d'or
Un droit (`Subscription`) n'est **jamais** activé sur simple déclaration : toujours vérifier la transaction réelle auprès du fournisseur de paiement (console marchand / API) et rapprocher avec `Payment.provider_reference`.

## 1. Paiement débité mais abonnement non activé (webhook manqué)
1. Récupérer la référence interne ou la référence opérateur Mobile Money fournie par le pro (SMS de confirmation MTN MoMo / Orange Money).
2. Dans `/<ADMIN_URL>` → **Facturation (`billing`) → Paiements**, rechercher la transaction et noter `provider`, `provider_reference` et `status`.
3. Vérifier dans le tableau de bord du fournisseur (CinetPay, Notch Pay, Campay…) que la transaction est bien `SUCCEEDED` / `PAID`.
4. Vérifier les journaux pour comprendre pourquoi le webhook a échoué :
   ```bash
   docker compose -f compose.prod.yaml logs --tail=200 web worker | grep -iE "billing|webhook|payment"
   ```
5. Déclencher la revérification / réconciliation via la tâche prévue ou le shell Django (`billing.services`), afin de passer le `Payment` à `succeeded` et d'activer la `Subscription` de manière idempotente (sans créer de doublon).

## 2. Double débit
1. Confirmer auprès du fournisseur qu'il existe bien **deux** transactions `PAID` distinctes pour la même période/commande.
2. Initier le remboursement de la transaction excédentaire depuis la console du fournisseur (ou via son API).
3. Marquer le second `Payment` en `refunded` dans l'admin sans désactiver la `Subscription` valide.

## 3. Remboursement total d'un abonnement
1. Effectuer le remboursement côté fournisseur Mobile Money.
2. Mettre le `Payment` à `refunded`.
3. Clôturer / annuler la `Subscription` associée : le profil revient automatiquement au plan **Gratuit** (le contenu, l'URL et les cartes restent actifs ; seuls les droits payants sont désactivés).
4. Enregistrer la trace du remboursement (date, référence, motif) pour la comptabilité.
