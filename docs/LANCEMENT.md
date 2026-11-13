# Lancer et tester Modulis Profils en local

Toutes les commandes se tapent dans **Ubuntu (WSL)**. Ouvrez un terminal Ubuntu, ou tapez `wsl` dans PowerShell.

## 1. Démarrer

```bash
cd /mnt/c/Users/HP/Desktop/modulis-profils
make up
```

`make up` construit les images et démarre 4 conteneurs : `web` (Django), `worker` (tâches Huey), `db` (PostgreSQL 17)
et `redis` (Redis 7). Les migrations s'appliquent automatiquement.

| Adresse | Quoi |
|---|---|
| http://localhost:8000/ | accueil de la plateforme |
| http://localhost:8000/espace/connexion | espace pro (connexion par code) |
| http://localhost:8000/gestion/ | administration |
| http://localhost:8000/gestion/centre-de-controle/ | centre de contrôle (activer / désactiver les fonctions) |

## 2. Données de démonstration (une seule fois)

```bash
make dmanage cmd=seed_demo
```

La commande affiche :
- le **compte administrateur** (`+237690000100`) et son **mot de passe**, généré au hasard et affiché une seule fois ;
- 4 pages de démonstration (`/ange-kenmogne`, `/brenda-atangana`, `/kevin-ndjock`, `/salon-belle-allure`) ;
- des **cartes NFC de démonstration** : adresse `/c/CODE` et code d'activation.

Mot de passe perdu ? `make dmanage cmd="changepassword +237690000100"`.

## 2 bis. Se connecter à l'administration (double authentification)

L'administration (`/gestion/` en local, adresse **secrète** `ADMIN_URL` en production) exige **mot de passe +
double authentification (TOTP)** pour tout compte de l'équipe, y compris le compte de démonstration :

1. Créez un compte d'équipe avec `make admin` (ou utilisez celui de `seed_demo`).
2. Installez une application d'authentification sur votre téléphone : Google Authenticator, Microsoft Authenticator
   ou Aegis.
3. Ouvrez http://localhost:8000/gestion/, saisissez le numéro et le mot de passe.
4. **Première connexion** : scannez le QR code affiché, saisissez le code à 6 chiffres, puis notez ou téléchargez les
   **10 codes de secours** (affichés une seule fois).
5. **Connexions suivantes** : saisissez le code à 6 chiffres de l'application après le mot de passe.

Téléphone perdu : un code de secours remplace le code de l'application ; un super-administrateur peut aussi
« Réinitialiser la double authentification » du compte (liste des utilisateurs). En développement seulement, la 2FA
peut être coupée avec `STAFF_2FA_REQUIRED=False` dans `.env`. Tout le détail : `docs/SECURITE-ADMIN.md`.

## 3. Se connecter comme un pro

1. Ouvrez http://localhost:8000/espace/connexion et entrez un numéro camerounais (ex. `690 00 01 01`, le numéro de la page démo d'Ange).
2. Tant que WhatsApp et Firebase ne sont pas configurés, le code s'affiche **dans les journaux** :
   ```bash
   make logs
   ```
3. Saisissez le code : vous arrivez dans votre espace (onboarding, visite guidée, modèles, cartes…).

Un numéro inconnu crée automatiquement un compte, puis la page via l'onboarding.

## 4. Tester une carte NFC

Ouvrez une adresse `http://localhost:8000/c/CODE` affichée par `seed_demo`. Saisissez son code d'activation, votre numéro,
puis le code reçu : la carte est liée à la page. Les scans suivants redirigent directement vers la page.

## 5. Activer WhatsApp et le SMS Firebase

Remplissez les variables `WHATSAPP_*` et `FIREBASE_*` du fichier `.env` (étapes détaillées dans `.env.example` et
`docs/adr/0009-otp-whatsapp-firebase.md`), puis :

```bash
docker compose up -d
```

Activez ensuite les canaux dans le **centre de contrôle**.

## 6. Commandes utiles

| Commande | Rôle |
|---|---|
| `make logs` | journaux du serveur et du worker (codes de connexion en dev) |
| `make admin` | créer un compte de l'équipe (administration : mot de passe + double authentification) |
| `make down` | tout arrêter (les données sont conservées) |
| `make test` | tests rapides (venv WSL, SQLite) |
| `make dtest` | tests dans Docker, sur PostgreSQL |
| `make check` | lint + vérifications Django + migrations + tests + couverture |
| `make dmanage cmd="seo_audit --crawl"` | audit SEO automatique des pages publiques |
| `make dshell` | console Django |
| `make pages` | parcours de toutes les pages (public, espace pro, admin) : liste les erreurs |
| `make backup` / `make backup-list` | sauvegarde immédiate base + photos hors Docker / inventaire |
| `make backup-verify` | restauration test de la dernière sauvegarde (base jetable) |
| `make restore name=latest` | restaurer une sauvegarde (voir [SAUVEGARDES.md](SAUVEGARDES.md)) |
| `docker compose down -v` | tout supprimer, **données comprises** : seulement après `make backup` + `make backup-verify` |

## Après une mise à jour du code

Le serveur et le worker se rechargent tout seuls. Si le `Dockerfile`, `entrypoint.sh` ou les dépendances changent,
reconstruisez les images :

```bash
make up        # sauvegarde automatique, puis reconstruction
```

Erreur « column … does not exist » ou « relation … does not exist » : le code attend une migration
que la base n'a pas encore. Appliquez-la : `make dmanage cmd=migrate` (elle s'applique aussi seule au
redémarrage du service `web`).

En cas de problème, le **centre de contrôle → Santé de la plateforme** vérifie la base, le cache, le **stockage des
fichiers** (envoi de photos) et les tâches de fond.

## Sauvegardes (hors Docker)

Le service `backup` sauvegarde chaque nuit à 02:30 la base et les photos dans `./backups`
(dossier du projet sur le disque Windows, hors des volumes Docker), avec rotation 7 jours / 4 semaines /
12 mois, empreintes SHA-256 et restauration test chaque dimanche. Tout est décrit dans
[SAUVEGARDES.md](SAUVEGARDES.md) (chiffrement, copie hors site, reprise après sinistre).

## Pages légales

`/cgu`, `/confidentialite` et `/mentions-legales`. Renseigner l'identité de l'entreprise
(RCCM, NIU, siège, directeur de la publication, hébergeur) dans `.env`, variables `LEGAL_*` :
les champs vides sont masqués. Quand le texte change, augmenter `LEGAL_VERSION` dans
`apps/legal/conf.py` : chaque pro devra accepter la nouvelle version à sa prochaine visite.

## Ports

- Site : `8000` (`WEB_HOST_PORT=8001 make up` pour en changer).
- PostgreSQL : `5433` côté Windows (`POSTGRES_HOST_PORT`), parce que le port 5432 est déjà utilisé sur ce poste.

## Captures d'écran

Elles sont dans `docs/captures/`. Elles ont été prises sur cet environnement Docker avec les données de démonstration.
