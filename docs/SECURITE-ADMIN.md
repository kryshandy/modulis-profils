# Accès et sécurité de l'administration

Ce document explique **comment l'équipe Modulis accède à l'administration** (tableau de bord, centre de contrôle,
journal) et **quelles protections** l'entourent, avec l'endroit du code où chacune se trouve.
Décision d'architecture : [ADR-0010](adr/0010-double-authentification-equipe.md).

---

## 1. Où se trouve l'administration ?

| Environnement | Adresse |
|---|---|
| Développement (Docker) | http://localhost:8000/gestion/ |
| Production | `https://<domaine>/<ADMIN_URL>` — adresse **secrète**, définie dans le `.env` du serveur |

En production, `ADMIN_URL` **doit** être une adresse difficile à deviner, par exemple `gestion-7k2m9q4x8p3z/`
(un segment aléatoire d'au moins 12 lettres et chiffres). Le serveur **refuse de démarrer** avec la valeur par défaut
`gestion/` ou un mot courant (`admin/`, `administration/`…). Ne communiquez cette adresse qu'aux membres de l'équipe.

Générer une adresse :
```bash
python3 -c "import secrets, string; a = string.ascii_lowercase + string.digits; print('gestion-' + ''.join(secrets.choice(a) for _ in range(16)) + '/')"
```

## 2. Créer un compte pour un membre de l'équipe

Les professionnels créent leur compte eux-mêmes, par code WhatsApp/SMS. **L'équipe, jamais** : un compte d'équipe se
connecte uniquement avec un **mot de passe + la double authentification**.

**Depuis le serveur (premier compte, ou à tout moment)** :
```bash
make admin
```
(équivaut à `docker compose exec web python manage.py create_staff`). La commande demande :
- le numéro de téléphone (format international, ex. `+237690000100`) — c'est l'identifiant de connexion ;
- le nom complet ;
- s'il s'agit d'un **super-administrateur** (tous les droits) ;
- le mot de passe, deux fois (12 caractères minimum, ni trop courant, ni uniquement des chiffres, ni proche du nom).

Elle affiche ensuite l'étape suivante : « connectez-vous à /<ADMIN_URL> et scannez le QR code ».

Version sans question (scripts) : le mot de passe est lu dans une variable d'environnement, jamais sur la ligne de
commande :
```bash
docker compose exec -e DJANGO_STAFF_PASSWORD='…' web python manage.py create_staff \
    --phone +237690000100 --full-name "Awa Ndi" --superuser --no-input
```

**Depuis l'administration** : Utilisateurs → « Ajouter » crée un compte d'équipe (numéro + mot de passe). Attribuez
ensuite ses droits avec un **groupe** (section « Équipe Modulis » de la fiche) : un compte sans groupe ne voit rien.

**Compte de démonstration** : `make dmanage cmd=seed_demo` crée l'administrateur `+237690000100` avec un mot de passe
affiché une fois. Comme tout compte d'équipe, il devra **activer la double authentification à sa première connexion**.

## 3. Première connexion : activer la double authentification

1. Installez sur votre téléphone une application d'authentification : **Google Authenticator**, **Microsoft
   Authenticator** ou **Aegis** (Android, libre). Toute application compatible « TOTP » convient.
2. Ouvrez l'adresse de l'administration, saisissez votre numéro et votre mot de passe.
3. La page **« Activer la double authentification »** s'affiche automatiquement : scannez le **QR code** avec
   l'application (ou saisissez la clé affichée en dessous, type « basé sur le temps »).
4. Saisissez le **code à 6 chiffres** affiché par l'application, puis « Activer ».
5. **10 codes de secours** s'affichent, **une seule fois**. Téléchargez-les (.txt) ou recopiez-les, et rangez-les
   **hors du téléphone** (gestionnaire de mots de passe, papier dans un endroit sûr). Chaque code ne sert qu'une fois.
6. Cliquez « Mes codes sont en lieu sûr » : vous arrivez dans l'administration.

## 4. Connexions suivantes

Numéro + mot de passe, puis la page **« Vérification en deux étapes »** : saisissez le code à 6 chiffres de
l'application. Chaque nouvelle connexion par mot de passe redemande un code. La session dure **8 heures** au plus.

- **5 codes faux en 10 minutes** (pour un compte, depuis un même appareil) bloquent la vérification 10 minutes, avec
  un message clair. Cause fréquente : l'heure du téléphone n'est pas automatique.
- Un même code ne peut pas servir deux fois (anti-rejeu).
- Vos codes de secours restants et le bouton « Générer de nouveaux codes » sont sur la page
  `/<ADMIN_URL>securite/2fa/`.

## 5. Téléphone perdu ou changé

1. **Avec un code de secours** : sur la page de vérification, saisissez un code de secours (ex. `abcd-efgh`) à la place
   du code de l'application. Allez ensuite sur `/<ADMIN_URL>securite/2fa/` pour générer de nouveaux codes, et
   demandez une réinitialisation pour enregistrer le nouveau téléphone (étape 2).
2. **Réinitialisation par un super-administrateur** : Utilisateurs → cocher le compte → action
   **« Réinitialiser la double authentification »**. Les appareils du compte sont supprimés, toutes ses sessions
   fermées ; à sa prochaine connexion, la personne scanne un nouveau QR code. L'action est réservée aux
   super-administrateurs, **impossible sur son propre compte**, et inscrite au journal.
3. **Dernier recours** (le seul super-administrateur a tout perdu) : sur le serveur,
   ```bash
   docker compose exec web python manage.py shell -c "from django_otp.plugins.otp_totp.models import TOTPDevice; from django_otp.plugins.otp_static.models import StaticDevice; TOTPDevice.objects.filter(user__phone='+2376…').delete(); StaticDevice.objects.filter(user__phone='+2376…').delete()"
   ```
   puis reconnectez-vous et scannez un nouveau QR code. **Gardez au moins deux super-administrateurs** pour ne jamais en
   arriver là.

En cas de téléphone **volé**, changez aussi votre mot de passe (ci-dessous) et prévenez un super-administrateur.

## 6. Changer de mot de passe

- Soi-même : menu en haut à droite de l'administration → « Modifier le mot de passe ».
- Pour un autre membre (super-administrateur) : fiche de l'utilisateur → lien « formulaire » sous le mot de passe ;
  ou sur le serveur : `make dmanage cmd="changepassword +2376…"`.
- Après un départ de l'équipe : action « Désactiver (et déconnecter) » sur le compte, plutôt que la suppression
  (le journal garde l'auteur des actions passées).

---

## 7. Les couches de sécurité, et où elles se trouvent

| # | Protection | Détail | Code |
|---|---|---|---|
| 1 | **Jamais de code SMS/WhatsApp pour l'équipe** | Un compte d'équipe (ou désactivé) ne peut pas se connecter par code : refusé **avant** tout envoi (échange de SIM, numéro recyclé, console d'un fournisseur). | `apps/accounts/services.py` → `ensure_sms_login_allowed` |
| 2 | **Mot de passe robuste** | 12 caractères minimum, refus des mots de passe courants, uniquement numériques ou proches du nom. Hachage PBKDF2 de Django. | `config/settings/base.py` → `AUTH_PASSWORD_VALIDATORS` |
| 3 | **Limite des essais de mot de passe** | 10 envois du formulaire par heure et par IP (IPv6 regroupée par /64), compteur atomique Redis, puis page « Trop de tentatives » (HTTP 429). | `apps/core/middleware.py` → `AdminLoginThrottleMiddleware` |
| 4 | **Double authentification TOTP obligatoire** | Activation forcée à la première connexion, vérification à chaque connexion. Toute URL de l'administration (centre de contrôle compris) est bloquée tant que la session n'est pas vérifiée — **deux verrous** indépendants. 5 essais / 10 min par compte et IP, anti-rejeu, rotation de la clé de session, 10 codes de secours à usage unique. | `apps/security/` (services, vues, `admin.py`), `apps/core/middleware.py` → `StaffTwoFactorMiddleware`, `templates/admin/security/` |
| 5 | **Sessions courtes** | 8 h pour l'équipe (30 jours pour les pros sur leur téléphone). Chaque connexion par mot de passe efface la vérification 2FA précédente. | `apps/core/signals.py`, `STAFF_SESSION_AGE` |
| 6 | **Permissions par action** | Chaque action d'administration déclare la permission nécessaire (désactiver, bloquer un numéro, effacer une page…) ; le centre de contrôle exige `manage_platform`. Vérifié par un test. | `apps/*/admin.py` (`@admin.action(permissions=…)`), `apps/platform/views.py` → `can_manage`, `apps/core/tests/test_admin_hardening.py` |
| 7 | **Protection des super-administrateurs** | Seul un super-administrateur modifie un super-administrateur ; les champs de privilèges (super-admin, groupes, permissions) sont en lecture seule pour les autres et sur son propre compte ; les actions de masse ignorent son propre compte ; la réinitialisation 2FA est réservée aux super-administrateurs et interdite sur soi. | `apps/accounts/admin.py` → `has_change_permission`, `get_readonly_fields`, `_targets`, `reset_two_factor` |
| 8 | **Journal d'administration** | Qui a fait quoi : interrupteurs du centre de contrôle, blocages, désactivations, droits modifiés, suppressions, et pour la 2FA : `2fa.enroll`, `2fa.verify_failed`, `2fa.locked`, `2fa.backup_code_used`, `2fa.backup_codes_regenerated`, `2fa.reset`, `user.create_staff`. Lecture seule. | `apps/platform/services.py` → `audit`, `apps/platform/models.py` → `AuditLog` |
| 9 | **CSP stricte** | Aucun script ni style en ligne, aucune ressource externe ; le QR code est un SVG généré sur le serveur (`segno`), jamais par un service tiers. Pages interdites en `<iframe>`. | `config/settings/base.py` → `CONTENT_SECURITY_POLICY`, `X_FRAME_OPTIONS` |
| 10 | **HTTPS, HSTS, cookies sécurisés** | En production : redirection HTTPS, HSTS 1 an (sous-domaines, preload), cookies de session et CSRF `Secure`, `HttpOnly`, `SameSite=Lax`. | `config/settings/prod.py`, `config/settings/base.py` |
| 11 | **Adresse secrète** | `ADMIN_URL` aléatoire obligatoire en production (démarrage refusé sinon). Ce n'est pas une protection à elle seule, mais elle évite les robots qui attaquent `/admin/`. | `config/settings/prod.py` |
| 12 | **2FA impossible à couper en production** | `STAFF_2FA_REQUIRED=False` n'est accepté qu'en développement ; la production refuse de démarrer. | `config/settings/prod.py` |
| 13 | **Maintenance : l'équipe passe** | En mode maintenance, le public voit une page 503 ; l'équipe connectée continue d'utiliser le site, et l'administration reste accessible (avec mot de passe + 2FA). | `apps/platform/middleware.py` → `MaintenanceModeMiddleware` |
| 14 | **Conteneurs sans root** | Le serveur et le worker tournent sous l'utilisateur `app` (droits retirés au démarrage par `setpriv`). | `docker/django/Dockerfile`, `docker/django/entrypoint.sh` |
| 15 | **Secrets dédiés** | Clés HMAC des codes, des cartes, des slugs et sel des statistiques distincts de `SECRET_KEY` (≥ 32 caractères) en production. | `config/settings/prod.py` |
| 16 | **Pas de secret 2FA visible dans l'admin** | Les écrans d'appareils de django-otp sont retirés : ni clé TOTP, ni QR code, ni code de secours consultables. | `apps/security/admin.py`, `OTP_ADMIN_HIDE_SENSITIVE_DATA` |

### Recommandations pour la production

- **Sauvegardes** : PostgreSQL + médias chaque jour, **chiffrées** et **hors du serveur** (`pg_dump` + `restic`,
  rétention 7 jours / 4 semaines / 12 mois, voir `docs/00-PLAN-COMPLET.md`). La base contient les secrets TOTP et les codes de
  secours : une sauvegarde en clair donnerait le second facteur de toute l'équipe. Testez une restauration chaque mois.
- **Au moins deux super-administrateurs**, chacun avec ses codes de secours rangés à part.
- **Filtrage réseau en plus** (recommandé) : restreindre l'adresse de l'administration à des IP connues ou la placer
  derrière Cloudflare Access.
- Relire le **journal d'administration** chaque semaine : une série de `2fa.verify_failed` ou `2fa.locked` sur un
  compte signale un mot de passe compromis → le changer.
- Un compte d'équipe sans 2FA activée apparaît dans la colonne « 2FA » de la liste des utilisateurs (et dans le
  résumé `apps.security.services.two_factor_summary()` destiné au centre de contrôle).
