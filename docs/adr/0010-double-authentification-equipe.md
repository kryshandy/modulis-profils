# ADR-0010 — Double authentification TOTP obligatoire pour l'équipe sur l'administration

Statut : Proposée · 2026-11-11 · Ferme le point I4 de la revue MVP (`docs/revues/2026-11-10-revue-mvp.md`).

## Contexte
L'administration (`/<ADMIN_URL>`, centre de contrôle compris) donne accès à toutes les données des pros, aux interrupteurs
de la plateforme (connexions, inscriptions, canaux OTP, maintenance) et aux actions sensibles (blocage de numéros,
effacement de pages). Jusqu'ici, un compte de l'équipe n'était protégé que par un **mot de passe** (12 caractères,
validateurs Django), une limite de 10 essais par heure et par IP, et des sessions de 8 h.

Un mot de passe seul ne résiste pas à l'hameçonnage, à la réutilisation d'un mot de passe déjà fuité ni à un poste
infecté. La revue MVP a laissé ouvert : « double authentification (TOTP) du personnel ».

Contraintes :
- l'équipe ne doit **jamais** se connecter par code SMS/WhatsApp (échange de SIM, numéro recyclé, console d'un
  fournisseur) : c'est déjà refusé par `accounts.services.ensure_sms_login_allowed` ;
- aucune ressource externe (CSP stricte : pas de script ni de style en ligne, pas de service de QR code tiers) ;
- installation simple pour une petite équipe, sans matériel à acheter au lancement.

## Décision
1. **TOTP (RFC 6238) obligatoire pour tout compte `is_staff`**, superutilisateurs compris, avec **django-otp 1.7**
   (`otp_totp` pour l'application d'authentification, `otp_static` pour 10 **codes de secours** à usage unique).
2. **Parcours** : mot de passe (inchangé, limité par `AdminLoginThrottleMiddleware`) → si aucun appareil confirmé :
   **activation forcée** (`/<ADMIN_URL>securite/2fa/activer/` : QR code SVG généré sur le serveur par `segno`, clé
   manuelle, confirmation par un code à 6 chiffres, puis 10 codes de secours affichés **une seule fois** et
   téléchargeables en .txt) ; sinon **vérification** (`/<ADMIN_URL>securite/2fa/verifier/` : code TOTP ou code de secours).
3. **Verrou à deux niveaux** jusqu'à la vérification de la session :
   - `apps.core.middleware.StaffTwoFactorMiddleware` redirige **toute** URL sous `ADMIN_URL` vers la bonne page 2FA
     (seuls restent ouverts : les pages 2FA, la déconnexion, l'envoi du formulaire de mot de passe) ;
   - `admin.site.has_permission` (étendu dans `apps/security/admin.py`) refuse aussi une session non vérifiée : même
     sans le middleware, aucune vue d'administration ne répond.
4. **Protections** : 5 essais par (compte, IP) sur 10 minutes, compteur atomique en cache (`cache.add` + `cache.incr`),
   puis blocage avec message clair (HTTP 429) ; anti-rejeu par `TOTPDevice.last_t` ; ralentissement exponentiel propre
   à chaque appareil (django-otp) ; **rotation de la clé de session** après vérification ; toute nouvelle connexion
   par mot de passe efface la vérification précédente (`apps/core/signals.py`).
5. **Journal** (`AuditLog`) : `2fa.enroll`, `2fa.verify_failed`, `2fa.locked`, `2fa.backup_code_used`,
   `2fa.backup_codes_regenerated`, `2fa.reset`, `user.create_staff`.
6. **Téléphone perdu** : action d'administration « Réinitialiser la double authentification », réservée aux
   **superutilisateurs**, jamais sur leur propre compte ; elle supprime les appareils, ferme toutes les sessions du
   compte et l'oblige à une nouvelle activation.
7. **Réglages** : `STAFF_2FA_REQUIRED` (vrai par défaut, désactivable en développement seulement — la production refuse
   de démarrer sinon), `OTP_TOTP_ISSUER = "Modulis Profils"`. La production exige aussi un `ADMIN_URL` secret
   (segment aléatoire d'au moins 12 lettres et chiffres).
8. Les administrations d'appareils fournies par django-otp sont **retirées** : aucun secret TOTP ni code de secours
   n'est visible dans l'admin.

## Alternatives écartées
- **django-two-factor-auth** : parcours complet mais lourd (formulaires multi-étapes, dépendance `qrcode`/phonenumbers,
  gabarits à réhabiller, SMS/appel proposés comme second facteur, contraire à notre règle) ; django-otp seul suffit.
- **Second facteur par SMS/WhatsApp** : vulnérable à l'échange de SIM, au numéro recyclé et aux consoles des
  fournisseurs ; explicitement interdit pour l'équipe.
- **Clés de sécurité WebAuthn/passkeys** : plus robustes contre l'hameçonnage mais demandent du JavaScript (CSP,
  aucun framework JS) et du matériel ; à reconsidérer quand l'équipe grandira (django-otp-webauthn).
- **Accès admin réservé à un VPN / Cloudflare Access** : excellent complément réseau, recommandé en production, mais ne
  remplace pas un second facteur lié à la personne.
- **Middleware seul** ou **AdminSite personnalisé seul** : un seul verrou peut sauter lors d'un refactoring ; les deux
  sont gardés (défense en profondeur), testés séparément.

## Conséquences
- Chaque membre de l'équipe installe une application d'authentification (Google Authenticator, Microsoft
  Authenticator, Aegis…) et garde ses codes de secours hors de son téléphone.
- Un superutilisateur seul qui perd téléphone **et** codes de secours ne peut plus entrer : il faut **au moins deux
  superutilisateurs**, ou une intervention serveur (`manage.py shell`, voir `docs/SECURITE-ADMIN.md`).
- Les secrets TOTP et les codes de secours sont stockés en clair dans la base (modèle django-otp) : les sauvegardes
  de la base sont sensibles et doivent être chiffrées.
- Les tests gardent la 2FA active : la fixture de `conftest.py` marque comme vérifiées les sessions d'équipe ouvertes
  par `force_login` (`apps.security.testing.mark_otp_verified`) ; les tests de la 2FA elle-même (`@pytest.mark.real_2fa`)
  passent par le vrai parcours.
- Nouvelle dépendance : `django-otp==1.7.5` ; tables `otp_totp_totpdevice`, `otp_static_staticdevice`,
  `otp_static_statictoken` (migrations fournies par django-otp).
