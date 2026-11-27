# Runbook 05 — Réception et contrôle d'un lot de cartes NFC

**Objectif** : valider la qualité physique, cryptographique et sécuritaire d'un lot de cartes livré par l'imprimeur/encodeur avant toute mise en vente.
**Référence** : [00-PLAN-COMPLET.md](../00-PLAN-COMPLET.md) (§ 4.3, § 12.1) · ADR-0005.

## 1. Contrôle physique et d'impression (échantillon ≥ 5 % ou min. 10 cartes)
- Vérifier la lisibilité du QR code imprimé sur plusieurs téléphones (iOS et Android).
- Vérifier que l'URL encodée dans le QR et dans la puce NFC correspond **exactement** au format figé :
  `https://<DOMAINE>/c/<CODE_7_CARACTERES>` (sans slash final, sans paramètre).
- Vérifier l'intégrité du masque à gratter (ou de l'emballage scellé) protégeant le code d'activation à 8 caractères.

## 2. Contrôle du verrouillage NFC (OBLIGATOIRE)
Une puce NTAG21x non verrouillée peut être réécrite par un tiers vers une URL de phishing.
1. Sur un smartphone équipé d'une application de lecture/écriture NFC (ex. *NFC Tools*), scanner au moins 5 cartes prises au hasard dans le lot.
2. Vérifier l'état de la puce : **`Writable: No` / `Locked: Yes` (lecture seule définitive)**.
3. Tenter d'écrire une URL de test : l'écriture **doit échouer**.
4. **Si une seule carte est modifiable** : **REFUSER le lot entier** et exiger le verrouillage matériel par le fournisseur avant réception.

## 3. Contrôle fonctionnel dans l'application
1. Scanner 2 cartes de test (sans les activer définitivement si destinées à la vente, ou en utilisant une carte témoin du lot) :
   - `/c/<CODE>` doit afficher la page d'activation (et **non** une 404).
   - Le code d'activation imprimé doit être accepté avant l'envoi d'OTP.
2. Dans `/<ADMIN_URL>` → **Cartes → Lots (`CardBatch`)**, noter le lot comme contrôlé (`nfc_locked=True` sur les cartes vérifiées / le lot).

## 4. Purge sécurisée du fichier d'export imprimeur (OBLIGATOIRE)
Le fichier CSV/PDF transmis à l'imprimeur contient les **codes d'activation en clair**.
1. Confirmer auprès de l'imprimeur la suppression définitive du fichier d'export de ses postes et messageries.
2. Supprimer le fichier CSV/PDF d'export du poste local et de toute boîte d'envoi.
3. En base, seuls les hachages des codes d'activation sont conservés (`activation_code_hash`).
