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
| `make down` | tout arrêter (les données sont conservées) |
| `make test` | tests rapides (venv WSL, SQLite) |
| `make dtest` | tests dans Docker, sur PostgreSQL |
| `make check` | lint + vérifications Django + migrations + tests + couverture |
| `make dmanage cmd="seo_audit --crawl"` | audit SEO automatique des pages publiques |
| `make dshell` | console Django |
| `docker compose down -v` | tout supprimer, **données comprises** (repartir de zéro) |

## Ports

- Site : `8000` (`WEB_HOST_PORT=8001 make up` pour en changer).
- PostgreSQL : `5433` côté Windows (`POSTGRES_HOST_PORT`), parce que le port 5432 est déjà utilisé sur ce poste.

## Captures d'écran

Elles sont dans `docs/captures/`. Elles ont été prises sur cet environnement Docker avec les données de démonstration.
