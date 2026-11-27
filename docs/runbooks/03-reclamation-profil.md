# Runbook 03 — Réclamation ou litige sur un profil

**Objectif** : traiter une contestation de propriété (usurpation d'identité, erreur de numéro saisi par un agent terrain, conflit entre deux professionnels sur un même nom/commerce).

## 1. Gel conservatoire (si usurpation suspectée)
En cas de signalement grave (arnaque, faux numéro WhatsApp redirigeant les clients) :
1. Ouvrir `/<ADMIN_URL>` → **Modération → Signalements** (ou **Profils**).
2. Passer le profil en statut **Suspendu** le temps de l'instruction (la page retourne **404** et ne sert aucun contenu).

## 2. Collecte des preuves
Demander au plaignant et/ou au titulaire actuel :
- Pièce d'identité (CNI / passeport) ou RCCM / patente pour une entreprise.
- Preuve de propriété du numéro de téléphone ou de l'enseigne.
- S'il s'agit d'une création par agent terrain : vérifier dans l'admin `created_by_agent` et la date de consentement OTP.

## 3. Résolution selon le cas
- **Cas A — Erreur de numéro par un agent terrain** :
  1. Vérifier que le vrai professionnel détient bien le bon numéro (appel ou message WhatsApp de vérification).
  2. Créer ou rattacher le profil au compte `User` correspondant au bon numéro E.164 (via les outils admin / service `profiles`).
  3. Nettoyer l'ancien compte erroné s'il n'a aucun autre profil ni carte active.
- **Cas B — Usurpation avérée** :
  1. Laisser le profil usurpateur **Suspendu** (ou **Supprimé** si demande d'effacement, ce qui retourne **410**).
  2. Désactiver toutes les cartes associées avec motif `fraude`.
  3. Bloquer le numéro fautif dans les contrôles OTP si récidive.
- **Cas C — Homonymie légitime (deux pros avec le même nom)** :
  - Chaque pro garde son propre profil ; les slugs restent distincts (`nom-metier`, `nom-metier-ville`). Ne pas transférer un slug existant sans accord écrit des deux parties.

## 4. Clôture
- Mettre à jour le statut du signalement dans **Modération** avec une note interne datée.
- Notifier les parties concernées par le canal officiel (email/WhatsApp support).
