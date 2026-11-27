# Runbook 06 — Suspension d'un profil frauduleux

**Objectif** : retirer immédiatement de la diffusion un profil utilisé pour de l'arnaque, du phishing ou du spam.
**Référence** : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 4, § 7).

## 1. Qualifier le signalement
1. Se connecter à `/<ADMIN_URL>` → **Modération → Signalements**.
2. Examiner le motif, le message du déclarant et le contenu actuel de la page (`display_name`, `bio`, liens sortants, photos).
3. En cas de doute avéré (usurpation d'un commerce connu, lien suspect, arnaque Mobile Money, contenu illégal), passer immédiatement à l'étape 2.

## 2. Suspendre le profil en un clic
1. Dans la fiche du `Profile` (ou depuis l'action de modération), passer `status` à **Suspendu** (`suspended`).
2. Effet immédiat vérifié par l'application :
   - `/<slug>` répond en **404** (aucun contenu servi, désindexé).
   - `/c/<CODE>` redirige vers une page « indisponible » (aucun scan vers le contenu frauduleux).
   - Le profil disparaît des sitemaps et de l'annuaire.

## 3. Actions complémentaires
- **Cartes associées** : si des cartes physiques ont été utilisées dans la fraude, les passer à **Désactivée** avec motif `fraude`.
- **Compte utilisateur** : si le numéro est clairement un compte d'arnaqueur récidiviste, bloquer le numéro pour empêcher de nouveaux OTP.
- **Moteurs de recherche** : si la page frauduleuse a déjà été indexée sur Google, demander le retrait temporaire dans Google Search Console (Outil « Suppressions ») en complément du code 404.

## 4. Traçabilité
- Clôturer le signalement dans **Modération** en précisant le motif et l'auteur de la décision.
- Ne **pas** supprimer le profil immédiatement si une enquête ou un litige est en cours (la suspension conserve les preuves en base sans rien exposer publiquement).
