# Runbook 04 — Numéro de téléphone recyclé

**Objectif** : gérer le cas où un opérateur télécom réattribue un numéro inactif à une nouvelle personne, afin d'éviter la prise de contrôle du profil de l'ancien titulaire.
**Référence** : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 7).

## Contexte
- Un compte est identifié par `phone_e164`.
- Sur un compte inactif depuis plus de 6 mois ou en cas de doute sur un nouvel appareil, une vérification supplémentaire est requise (email de récupération si renseigné, sinon revue manuelle).

## 1. Identifier la situation
Symptômes typiques :
- L'ancien titulaire contacte le support car il a changé de numéro et n'arrive plus à se connecter.
- Un nouvel utilisateur reçoit un OTP sur un numéro qui ouvre un profil appartenant déjà à quelqu'un d'autre.

## 2. Si le nouveau titulaire signale voir le profil d'un autre
1. **Suspendre temporairement** l'accès ou geler les modifications du profil existant pour protéger les données de l'ancien titulaire.
2. Contacter l'ancien titulaire via son **email de récupération** (s'il existe dans `User.email`) ou ses autres coordonnées publiques.
3. **Si l'ancien titulaire répond** :
   - Vérifier son identité.
   - Transférer son profil vers son **nouveau numéro E.164** (créer/vérifier le nouveau compte et réattribuer le `Profile` + les `Card` actives).
   - Libérer l'ancien `User` (ou le supprimer s'il est vide) pour que le nouveau titulaire puisse créer sa propre page vierge.
4. **Si l'ancien titulaire est injoignable après relance** :
   - Ne **jamais** donner l'accès à ses données privées, statistiques ou cartes au nouveau titulaire.
   - Archiver/supprimer l'ancien compte (le slug passe en `erased` → **410**), puis laisser le nouveau titulaire créer un nouveau profil vierge.

## 3. Si l'ancien titulaire prévient en amont de son changement de numéro
- Vérifier son identité (email de récupération ou code de carte physique détenue).
- Mettre à jour `User.phone_e164` vers le nouveau numéro validé en base.
