# ADR-0005 — Code d'activation secret par carte

Statut : Proposée · 2026-11-09

## Contexte
Le code public de la carte figure dans le QR et dans la puce NFC : n'importe qui peut le lire. Si l'activation ne demandait
que ce code, une personne pourrait scanner une carte invendue (en boutique, chez un revendeur) et se l'approprier.

## Décision
Chaque carte reçoit à la génération un code d'activation de 8 caractères, imprimé sous une zone à gratter ou sur un encart
dans l'emballage. Il est stocké sous forme d'**HMAC-SHA256 avec la clé secrète du serveur**. Un hachage lent de type
PBKDF2 aurait demandé plusieurs minutes pour générer un lot de 1 000 cartes ; la clé secrète suffit à rendre impossible une
attaque hors ligne. Il est vérifié **avant** tout envoi d'OTP, pour qu'une
carte invendue ne puisse pas servir à faire envoyer des SMS payants. Limite par couple (carte, IP) : 5 essais par heure.
Un seuil global par carte déclenche une alerte mais pas de blocage, sinon quiconque connaît le code public pourrait
bloquer le propriétaire légitime.
La puce NFC est **verrouillée en écriture** après encodage (critère d'acceptation du fournisseur). Le fichier d'export pour l'imprimeur est le seul endroit où il apparaît en clair ; il n'est jamais versionné
(dossier `exports/` ignoré par git) et est supprimé après impression.

## Conséquences
Un coût d'impression légèrement plus élevé, et un processus de manipulation des exports à respecter (runbook).
