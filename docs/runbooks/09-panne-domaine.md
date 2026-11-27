# Runbook 09 — Panne de domaine ou DNS

**Objectif** : rétablir au plus vite l'accès au domaine (critique : toutes les cartes NFC imprimées pointent vers `https://<domaine>/c/<code>`).
**Référence** : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 1, § 12.1, § 13).

## 1. Diagnostic rapide (2 minutes)
Exécuter depuis un poste externe :
```bash
dig +short <domaine> A
dig +short <domaine> NS
curl -I https://<domaine>/healthz
```
- **Le DNS ne résout plus (`NXDOMAIN` / `SERVFAIL`)** → problème registrar, expiration de domaine ou DNSSEC cassé (étape 2).
- **Le DNS résout vers Cloudflare mais erreur `521`/`522`/`523`/`525`/`526`** → problème entre Cloudflare et le VPS (étape 3).
- **Erreur de certificat TLS (`ERR_CERT_DATE_INVALID`)** → certificat expiré (étape 4).

## 2. Expiration ou blocage chez le registrar
1. Se connecter immédiatement au compte registrar (et/ou Cloudflare).
2. Vérifier le statut du domaine (`clientHold`, `pendingDelete`, `expired`) :
   - **Expiré** : renouveler immédiatement pour **5 à 10 ans** et activer le renouvellement automatique.
   - **`clientHold` (vérification WHOIS/ICANN en attente)** : valider le lien de confirmation dans la boîte email du titulaire du domaine.
   - **DNSSEC cassé** : vérifier la correspondance des enregistrements `DS` entre Cloudflare et le registrar (ou désactiver temporairement DNSSEC le temps du rétablissement).

## 3. Erreur Cloudflare ↔ Origine (521 / 522 / 525 / 526)
1. Vérifier sur le VPS que Nginx et Web tournent :
   ```bash
   docker compose -f compose.prod.yaml ps
   curl -fsS http://127.0.0.1/nginx-healthz
   ```
2. Vérifier que le pare-feu du VPS autorise bien les ports `80` et `443` (et les plages IP Cloudflare).
3. Vérifier le mode SSL Cloudflare (`Full (strict)` nécessite un certificat valide ou un *Cloudflare Origin Certificate* dans `docker/nginx/certs/`).

## 4. Certificat TLS expiré sur Nginx
1. Renouveler les certificats (Certbot / Origin Certificate Cloudflare) dans `docker/nginx/certs/fullchain.pem` et `privkey.pem`.
2. Recharger Nginx sans coupure :
   ```bash
   docker compose -f compose.prod.yaml exec nginx nginx -t && docker compose -f compose.prod.yaml exec nginx nginx -s reload
   ```

## 5. Prévention
- Conserver un rappel annuel dans le calendrier de maintenance : domaine payé pour 5 à 10 ans d'avance, renouvellement automatique activé, alerte Uptime Kuma sur l'expiration TLS (< 14 jours) et HTTP `/healthz`.
