# Runbooks opérationnels — Modulis Profils

Procédures d'exploitation et de réponse aux incidents pour la production (`compose.prod.yaml`).
Référence produit : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 12.2).

## Index des procédures

| # | Runbook | Quand l'utiliser |
|---|---|---|
| 01 | [Restauration d'une sauvegarde](01-restauration-sauvegarde.md) | Corruption de données, suppression accidentelle, sinistre serveur, test mensuel |
| 02 | [Carte NFC perdue ou volée](02-carte-perdue.md) | Un pro signale la perte ou le vol de sa carte et demande son remplacement |
| 03 | [Réclamation ou litige sur un profil](03-reclamation-profil.md) | Usurpation d'identité, erreur de numéro saisi par un agent terrain, conflit de propriété |
| 04 | [Numéro de téléphone recyclé](04-numero-recycle.md) | Un nouvel abonné opérateur récupère un ancien numéro déjà lié à un compte |
| 05 | [Réception et contrôle d'un lot NFC](05-controle-lot-nfc.md) | Livraison d'un lot imprimé/encodé : contrôle qualité, verrouillage NTAG21x, purge des codes |
| 06 | [Suspension d'un profil frauduleux](06-suspension-fraude.md) | Signalement d'arnaque, phishing, usurpation ou contenu illicite |
| 07 | [Incident ou remboursement de paiement](07-incident-paiement.md) | Échec webhook Mobile Money, double débit, remboursement ou correction d'abonnement |
| 08 | [Migration de serveur](08-migration-serveur.md) | Changement de VPS ou réinstallation complète avec zéro perte de données |
| 09 | [Panne de domaine ou DNS](09-panne-domaine.md) | Le domaine ne répond plus, expiration imminente, erreur SSL/Cloudflare |
| 10 | [Pic de trafic ou dégradation](10-pic-trafic.md) | Surcharge CPU/RAM, saturation Gunicorn/Redis/PostgreSQL, attaque ou viralité |
| 11 | [Fuite de données](11-fuite-donnees.md) | Compromission suspectée ou avérée de données personnelles (loi n° 2024/017) |

---

## Checklist `.env` de production

À vérifier **avant** tout démarrage avec `docker compose -f compose.prod.yaml up -d` (`config/settings/prod.py` refuse de démarrer si les contrôles critiques échouent).

### 1. Cœur Django & sécurité
- [ ] `DJANGO_SETTINGS_MODULE=config.settings.prod`
- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_SECRET_KEY` : chaîne aléatoire ≥ 50 caractères, unique à la production
- [ ] `DJANGO_ALLOWED_HOSTS` : domaine(s) exact(s), sans `*` (ex. `profils.cm,www.profils.cm`)
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` : origines HTTPS complètes (ex. `https://profils.cm`)
- [ ] `SITE_URL` : URL canonique HTTPS sans slash final (ex. `https://profils.cm`)
- [ ] `ADMIN_URL` : chemin secret non devinable se terminant par `/` avec au moins un segment ≥ 12 caractères alphanumériques (ex. `gestion-7k2m9q4x8p3z/`) — **jamais** `gestion/`
- [ ] `STAFF_2FA_REQUIRED=True` (obligatoire en prod, ADR-0010)
- [ ] `TRUSTED_PROXY_IPS` : IP du réseau Docker Nginx (ou plages Cloudflare si derrière Cloudflare) pour `X-Real-IP` / `CF-Connecting-IP`

### 2. Clés cryptographiques dédiées (distinctes de `DJANGO_SECRET_KEY`, ≥ 32 caractères)
- [ ] `OTP_HMAC_KEY`
- [ ] `ANALYTICS_SALT`
- [ ] `CARD_ACTIVATION_KEY` (ne **jamais** changer après impression de cartes)
- [ ] `SLUG_HASH_KEY`

### 3. Base de données & Cache
- [ ] `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (mot de passe fort)
- [ ] `DATABASE_URL=postgres://<user>:<password>@db:5432/<db>`
- [ ] `CACHE_URL=rediscache://redis:6379/0` (LocMem/Dummy interdits en prod)
- [ ] `REDIS_URL=redis://redis:6379/1`
- [ ] `HUEY_CLASS=huey.RedisHuey`

### 4. OTP, Anti-robots & SEO
- [ ] `SMS_BACKEND` : fournisseur réel ou `apps.accounts.sms.DisabledSmsBackend` (Console/Memory interdits)
- [ ] `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_OTP_TEMPLATE` (si WhatsApp actif)
- [ ] `FIREBASE_PROJECT_ID`, `FIREBASE_WEB_API_KEY`, `FIREBASE_WEB_AUTH_DOMAIN`, `FIREBASE_WEB_APP_ID` (si SMS Firebase actif)
- [ ] `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` (Cloudflare Turnstile actif avant tout OTP)
- [ ] `OTP_ALLOWED_PREFIXES=+237` et `OTP_MAX_SENDS_PER_DAY_GLOBAL` configurés
- [ ] `KLIZ_ENABLED=True`, `KLIZ_INDEXNOW_KEY`, `KLIZ_GSC_SITE`, `KLIZ_GSC_SERVICE_ACCOUNT_FILE`

### 5. Sauvegardes & Mentions légales
- [ ] `BACKUP_DIR` : chemin hôte sur un **autre disque** que les volumes Docker (ex. `/srv/sauvegardes/modulis`)
- [ ] `BACKUP_REQUIRE_ENCRYPTION=1` et `BACKUP_PASSPHRASE` forte (copiée dans le gestionnaire de mots de passe hors serveur)
- [ ] `RCLONE_REMOTE` et `RCLONE_CONFIG_DIR` configurés pour la copie hors site
- [ ] `LEGAL_FORM`, `LEGAL_RCCM`, `LEGAL_NIU`, `LEGAL_ADDRESS`, `LEGAL_PUBLICATION_DIRECTOR`, `LEGAL_HOST_NAME` renseignés (`python manage.py check --deploy` sans avertissement `legal.W001`)
- [ ] Super-admin d'évaluation supprimé (`BOOTSTRAP_ADMIN_PASSWORD` vide)
