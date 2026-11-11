# ADR-0009 — Codes de connexion par WhatsApp (Cloud API) ou par SMS (Firebase), canaux pilotés depuis l'admin

Statut : Proposée · 2026-11-10 · Remplace la ligne A18 du plan (« OTP par SMS uniquement ») et précise ADR-0004.

## Contexte
Le plan v1.2 avait retenu l'OTP **par SMS uniquement**, via un agrégateur local restant à choisir (question Q3). Depuis :
- au Cameroun, WhatsApp est installé sur la quasi-totalité des téléphones de nos pros ; un message d'authentification
  WhatsApp coûte nettement moins cher qu'un SMS international, arrive plus vite et plus sûrement (pas de filtrage
  opérateur, pas de SMS perdus) et se copie d'un geste (bouton « copier le code ») ;
- un agrégateur SMS local demande un contrat, un backend sur mesure et un budget prépayé, alors que Firebase
  Authentication fournit l'envoi et la vérification des SMS avec reCAPTCHA intégré, sans contrat ;
- le porteur veut pouvoir **activer ou couper chaque canal** depuis le centre de contrôle (incident chez un fournisseur,
  fraude, coût), sans redéploiement.

## Décision
1. **Trois canaux derrière une interface** (`apps/accounts/otp/`) :
   - **WhatsApp** (canal « serveur », recommandé, proposé par défaut) : API Cloud de Meta, modèle d'**authentification**
     approuvé avec bouton « copier le code » ; notre serveur génère le code (stocké en HMAC), l'envoie dans une tâche Huey
     avec nouvelles tentatives sur les erreurs passagères ; les erreurs de Meta sont traduites en messages sûrs
     (« pas de compte WhatsApp ? choisis le SMS ») et le pro peut basculer de canal depuis l'écran du code ;
   - **SMS via Firebase Authentication** (canal « client », repli) : le navigateur demande l'envoi et la vérification à
     Firebase (SDK modulaire officiel épinglé, reCAPTCHA invisible), puis transmet le **jeton d'identité Firebase** à
     notre serveur, qui le vérifie **sans `firebase-admin`** (PyJWT : RS256, `kid` parmi les certificats publics de
     Google mis en cache selon `Cache-Control`, `aud`, `iss`, `exp`, `iat`, `auth_time` récent, `sub`,
     `sign_in_provider == "phone"`, `phone_number` identique au numéro accepté par nos contrôles) ;
   - **SMS via passerelle** (canal « serveur », optionnel) : l'ancien `SMS_BACKEND`, conservé pour un futur agrégateur.
   - En développement uniquement, si aucun canal réel n'est disponible : un canal « console » affiche le code dans les logs.
2. **Mêmes règles pour tous les canaux**, appliquées par `request_otp` **avant tout envoi** (y compris avant que le
   navigateur ne sollicite Firebase, grâce à un défi « en attente » enregistré côté serveur) et revérifiées à la
   validation : liste blanche d'indicatifs, plafonds par numéro / IP / jour, refus des comptes équipe et désactivés,
   numéros bloqués (message générique), interrupteurs `login_enabled` et `signups_enabled`. Le jeton Firebase n'ouvre une
   session que s'il correspond à un défi en attente, non expiré, à usage unique, pour le même numéro et le même but.
3. **Secrets dans l'environnement, interrupteurs dans l'admin** : jetons et identifiants (`WHATSAPP_*`, `FIREBASE_*`)
   restent dans `.env` ; `SiteSettings` (app `platform`) porte uniquement l'activation de chaque canal et le canal par
   défaut. Un canal n'est proposé que s'il est **activé ET configuré** ; `channel_status()` expose cet état au centre de
   contrôle. Aucune de ces variables n'est obligatoire en production : un canal non configuré est simplement absent.
4. La CSP n'est élargie **que** pour Firebase et son reCAPTCHA (`www.gstatic.com`, `www.google.com`, `apis.google.com`,
   `identitytoolkit` / `securetoken.googleapis.com`, `www.googleapis.com`, cadres `www.google.com` et
   `*.firebaseapp.com`). Le SDK n'est chargé que sur l'écran du code quand le canal Firebase est choisi ; les pages
   publiques n'en chargent rien.

## Alternatives écartées
- **SMS uniquement par agrégateur local** (plan v1.2) : coût et délivrabilité moins bons, contrat et développement à
  prévoir avant le lancement ; gardé comme canal optionnel.
- **`firebase-admin`** pour vérifier les jetons : dépendance lourde (Google Cloud SDK) et compte de service à protéger,
  alors que la vérification documentée par Firebase avec une bibliothèque JWT tient en quelques lignes testées.
- **Firebase pour WhatsApp aussi** : Firebase n'envoie pas de WhatsApp.
- **WhatsApp via un fournisseur tiers (BSP)** : surcoût et intermédiaire de plus, l'API Cloud de Meta suffit.

## Conséquences
- Mise en place côté porteur : application Meta (WhatsApp Business), numéro expéditeur, jeton d'utilisateur système,
  modèle d'authentification approuvé en français ; projet Firebase avec le fournisseur « Téléphone », domaines
  autorisés, **politique de région SMS limitée au Cameroun** et quotas.
- Le SMS Firebase dépend de JavaScript et des domaines Google : sans JavaScript, l'écran invite à choisir WhatsApp.
- Quelqu'un qui récupère la clé web publique peut solliciter Firebase directement (hors de nos plafonds) : ce n'est pas
  un accès à notre plateforme (aucune session sans défi en attente côté serveur), mais cela peut coûter des SMS.
  Parades : politique de région SMS, quotas Firebase, App Check (reCAPTCHA Enterprise) à activer si des abus apparaissent.
- Suivi : taux de délivrance et coût par canal, erreurs Meta dans les logs (code d'erreur et `fbtrace_id`, jamais le
  code ni le jeton).
- `OTPChallenge` gagne un champ `channel` (migration `accounts.0002`).
