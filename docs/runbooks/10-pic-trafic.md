# Runbook 10 — Pic de trafic ou dégradation

**Objectif** : absorber un pic de trafic légitime (campagne, viralité) ou bloquer une attaque (DDoS / scraping / SMS pumping) sans faire tomber la base ni exploser les coûts OTP.

## 1. Identifier la nature du pic
```bash
# État des conteneurs et consommation CPU/RAM
docker stats --no-stream

# Dernières requêtes Nginx (codes HTTP, IPs, URLs les plus appelées)
docker compose -f compose.prod.yaml logs --tail=500 nginx
```
- **Trafic massif sur `/<slug>` ou `/villes/...`** → pic de lecture (viralité ou bot de crawl).
- **Trafic massif sur `/c/...` ou `/espace/connexion`** → possible tentative d'énumération ou attaque SMS pumping.
- **CPU saturé par `db`** → requêtes lentes ou connexions saturées.

## 2. Mesures immédiates côté Cloudflare / Nginx
- **Si attaque ou bot agressif** :
  - Activer le mode **« Under Attack »** dans Cloudflare (ou renforcer les règles WAF / Rate Limiting sur `/c/` et `/espace/connexion`).
  - Vérifier que Turnstile est actif (`TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` configurés) et que `OTP_MAX_SENDS_PER_DAY_GLOBAL` protège la facture OTP.
- **Si trafic légitime élevé sur les pages publiques** :
  - Vérifier que Cloudflare met bien en cache les pages publiques (statut `CF-Cache-Status: HIT`) et que `nginx` sert `/static/` et `/media/` directement.

## 3. Augmenter la capacité applicative (sans reconstruction)
1. Augmenter le nombre de workers Gunicorn dans `.env` (règle indicative : `2 × CPU + 1`, si la RAM le permet) :
   ```dotenv
   GUNICORN_WORKERS=5
   ```
2. Redémarrer uniquement `web` :
   ```bash
   docker compose -f compose.prod.yaml up -d --no-deps web
   ```
3. Vérifier la santé de PostgreSQL et Redis :
   ```bash
   docker compose -f compose.prod.yaml exec db pg_isready -U modulis -d modulis_profils
   docker compose -f compose.prod.yaml exec redis redis-cli info memory | grep used_memory_human
   ```

## 4. Mode dégradé (en dernier recours)
- Activer le mode maintenance depuis `/<ADMIN_URL>` → Centre de contrôle si la base est menacée de saturation, ou couper temporairement les inscriptions/OTP non essentiels depuis le centre de contrôle.
- Une fois le pic passé, revenir au dimensionnement normal et analyser la cause dans les journaux.
