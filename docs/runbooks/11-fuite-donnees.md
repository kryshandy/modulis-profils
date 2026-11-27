# Runbook 11 — Fuite de données (procédure d'incident et de notification)

**Objectif** : contenir immédiatement une compromission suspectée ou avérée, préserver les preuves, révoquer les secrets et notifier les personnes concernées conformément à la loi camerounaise n° 2024/017 sur la protection des données personnelles.
**Référence** : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 7, § 12.2).

## 1. Contenir l'incident (premiers 15 minutes)
1. **Ne pas éteindre brutalement** les conteneurs avant d'avoir sauvegardé les journaux si une analyse forensique est nécessaire.
2. Si une exfiltration active est en cours :
   - Activer le mode maintenance dans `/<ADMIN_URL>` ou couper l'accès public via Nginx/Cloudflare.
   - Bloquer l'IP ou le compte compromis.
3. Sauvegarder les preuves :
   ```bash
   mkdir -p /tmp/incident-$(date +%F)
   docker compose -f compose.prod.yaml logs > /tmp/incident-$(date +%F)/compose.log
   ```

## 2. Évaluer l'étendue et révoquer les secrets
Identifier quelles données ont été exposées (numéros `phone_e164`, emails, profils privés, sauvegardes non chiffrées, `.env`) :
1. **Rotation immédiate des secrets compromis** dans `.env` :
   - `DJANGO_SECRET_KEY` (invalide toutes les sessions actives)
   - `POSTGRES_PASSWORD`, `WHATSAPP_ACCESS_TOKEN`, `TURNSTILE_SECRET_KEY`, `OTP_HMAC_KEY`
   - ⚠️ **Attention** : ne changer `CARD_ACTIVATION_KEY` et `SLUG_HASH_KEY` que si ces clés mêmes ont fuité et après planification, car cela invalide les codes d'activation des cartes déjà imprimées.
2. **Comptes staff** : forcer la réinitialisation des mots de passe et des secrets 2FA TOTP de toute l'équipe.
3. **Sessions utilisateurs** : vider Redis (`FLUSHDB` sur la base de cache/sessions) pour déconnecter toutes les sessions.
4. Corriger la vulnérabilité à l'origine de la fuite et redéployer (`docker compose -f compose.prod.yaml up -d --build`).

## 3. Notification (obligations légales et transparence)
1. Documenter précisément : date de découverte, nature des données concernées, nombre approximatif de comptes affectés, mesures correctives prises.
2. **Autorité compétente** : notifier l'autorité de protection des données compétente au Cameroun dans les délais légaux applicables (loi n° 2024/017, avec validation juridique).
3. **Personnes concernées** : informer les professionnels affectés (par SMS/WhatsApp/email selon les canaux sûrs disponibles) en précisant :
   - ce qui a été exposé (et ce qui ne l'a pas été, ex. codes OTP hachés, aucune donnée bancaire stockée) ;
   - les précautions à prendre (vigilance face au phishing / faux messages se faisant passer pour Modulis).

## 4. Post-mortem
- Rédiger un rapport d'incident daté (cause racine, chronologie, actions préventives) et mettre à jour les tests de sécurité et la politique de confidentialité si nécessaire.
