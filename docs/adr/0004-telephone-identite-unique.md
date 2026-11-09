# ADR-0004 — Le téléphone vérifié est l'identité unique

Statut : Proposée · 2026-11-09

## Contexte
La spécification autorise l'inscription par téléphone **ou** par email. Le Point d'équipe pose « un numéro vérifié = un
compte » comme clé anti-doublon. Deux identifiants possibles produiraient des doublons (même personne, deux comptes).

## Décision
Le numéro de téléphone, normalisé en E.164 avec `phonenumbers` et vérifié par OTP, est obligatoire et unique (contrainte
en base). L'email est facultatif : il sert à la récupération du compte et aux reçus.

Le téléphone identifie le **compte**. Un compte peut porter plusieurs profils (personne + entreprise), selon l'offre.

## Conséquences
- Changement de numéro : procédure dédiée (OTP sur l'ancien et le nouveau numéro, ou vérification manuelle par le support).
- **Numéros recyclés** par les opérateurs : un compte inactif depuis plus de 6 mois, ou qui se connecte depuis un nouvel
  appareil, demande une vérification supplémentaire (email ou revue manuelle) ; le propriétaire est notifié.
- Coût des OTP à prévoir ; repli par WhatsApp ; protections contre la fraude aux SMS (+237 seul, Turnstile, plafonds).
- OTP stocké en HMAC avec un secret serveur.
