# CSS critique en ligne : pourquoi nous ne le faisons pas

> Note du 10 novembre 2026, suite à l'audit SEO (point 11).

## Constat

L'audit recommandait d'insérer le CSS critique dans le `<head>` des pages publiques pour gagner un aller-retour réseau
avant le premier affichage (LCP).

## Décision : `profile.css` reste une feuille externe

1. **CSP stricte.** Notre politique interdit tout style en ligne (`style-src 'self'`, sans `'unsafe-inline'`), règle
   non négociable de `CLAUDE.md`. Un bloc `<style>` exigerait un nonce ou une empreinte par réponse, ce qui
   complique le cache des pages et rouvre une surface d'attaque, pour un gain faible.
2. **Le fichier est petit.** `static/css/profile.css` pèse environ 6 Ko non compressé (moins de 2 Ko en gzip/Brotli).
   Une feuille bloquante de cette taille coûte un seul aller-retour, sans téléchargement notable.
3. **Cache long terme.** WhiteNoise (`CompressedManifestStaticFilesStorage`) sert le fichier sous un nom haché
   (`profile.<hash>.css`), précompressé et mis en cache pour un an (`immutable`). Dès la deuxième page vue, et pour
   chaque visiteur qui revient, la feuille ne coûte plus rien.
4. **`<link rel="preload" as="style">` ne sert à rien ici.** La feuille est déjà découverte par le parseur dans le
   `<head>`, à la première ligne utile : un préchargement ne la ferait pas arriver plus tôt.

## Ce que nous faisons à la place

- Aucun JavaScript bloquant (`profile.js` en `defer`), aucune police ni ressource externe.
- La photo du profil est préchargée avec `imagesrcset` et `imagesizes`, avec `fetchpriority="high"`.
- Les images sont responsives (`srcset` / `sizes` à partir des variantes WebP 160, 400 et 800 px), avec
  `width` et `height` toujours renseignés (pas de décalage de mise en page).
- Les pages publiques sont cachées au CDN (`s-maxage=600, stale-while-revalidate=86400`).

À réévaluer si `profile.css` dépasse environ 14 Ko compressé (première fenêtre TCP) ou si la CSP évolue.
