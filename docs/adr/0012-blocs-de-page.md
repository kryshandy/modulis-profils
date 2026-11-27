# ADR-0012 — Constructeur de page par blocs encadrés (`apps/blocks`)

- Statut : acceptée
- Date : 27 novembre 2026

## Contexte

Les pages publiques des professionnels reposent sur des modèles prédéfinis (`apps/themes`) dont les sections fixes (`about`, `services`, `gallery`, `hours`, `area`, `links`, `contact`) couvrent le socle métier. Plusieurs professionnels ont toutefois besoin d'enrichir leur page (présentation détaillée, questions fréquentes, avis clients, réalisations avant/après, étapes d'intervention, chiffres clés, vidéo de présentation, bannière d'appel).

Ouvrir un éditeur HTML/WYSIWYG libre ou autoriser du CSS/JS personnalisé casserait les garanties non négociables de la plateforme : rendu 100 % serveur, CSP stricte sans script ni style en ligne, accessibilité et hiérarchie sémantique (`h1` unique, `h2` par section), images légères en WebP, et SEO automatique fiable.

## Décision

Introduire une application dédiée `apps/blocks` proposant un **constructeur de page par blocs encadrés**, piloté par un registre Python déclaratif (`apps/blocks/registry.py`) :

### 1. Modèle de données et séparation contenu / ordre

- **`PageBlock`** (`apps/blocks/models.py`) : rattache un bloc à un `Profile`, identifié par un type `kind` issu de `BLOCK_TYPES`, un JSON `data` (contenu validé), un JSON `style` (options visuelles whitelistées), et les champs de modération (`moderated`, `moderation_note`).
- **`BlockImage`** (`apps/blocks/models.py`) : stocke les images associées à un bloc par `slot` unique (`image`, `before_0`, `after_0`, …), sous `profiles/<profile_id>/blocks/<uuid>.webp`.
- **Positionnement dans la page** : chaque bloc possède une clé `b<pk>` (`PageBlock.key`). L'ordre et la visibilité des blocs sont stockés aux côtés des sections fixes dans la configuration du thème (`apps.themes.services`). Lors de l'ajout d'un bloc (`add_block`), sa clé est insérée juste avant la section `contact` (`themes.insert_block_section`) ; lors de sa suppression (`delete_block`), elle en est retirée (`themes.remove_block_section`).

### 2. Registre des types de blocs (`apps/blocks/registry.py`)

Tout ce qu'un bloc peut contenir est déclaré dans `BLOCK_TYPES` via les dataclasses `BlockType`, `Field` et `Items`, avec des plafonds globaux par page : **`MAX_BLOCKS = 12`** et **`MAX_BLOCK_IMAGES = 30`** (`TITLE_MAX = 90`).

| `kind` | Libellé | Champs principaux | Éléments répétés (`Items`) | Images / Alignement |
|---|---|---|---|---|
| `text` | Texte | `title`, `body` (textarea, 3000) | — | Alignable |
| `text_image` | Texte + image | `title`, `body` (1500), `side` (`right` / `left`) | — | Slot `image` obligatoire |
| `banner` | Bannière d'appel | `title` (obligatoire), `text` (300), `button_action` (`whatsapp`/`call`/`link`/`none`), `button_label` (40), `button_url` (`url`, 300) | — | Alignable |
| `faq` | Questions fréquentes | `title` | `Question` (max 12) : `q` (160, req), `a` (800, req) | Génère du JSON-LD `FAQPage` |
| `testimonials` | Avis clients | `title` | `Avis` (max 8) : `quote` (400, req), `author` (60, req), `role` (80) | — |
| `before_after` | Avant / après | `title`, `intro` (300) | `Paire de photos` (max 4) : `caption` (120) | Slots `before` + `after` par item |
| `steps` | Étapes | `title` | `Étape` (max 6) : `title` (80, req), `text` (300) | — |
| `figures` | Chiffres clés | `title` | `Chiffre` (max 4) : `value` (12, req), `label` (60, req) | Alignable |
| `video` | Vidéo | `title`, `url` (`video`, 300, req), `caption` (300) | — | YouTube / Vimeo uniquement |

Les styles autorisés sont strictement bornés à `STYLE_CHOICES` (`background` : `auto`/`surface`/`primary`/`accent`/`ink` ; `spacing` : `compact`/`normal`/`airy` ; `align` : `start`/`center` si `alignable=True`), traduits en classes CSS `t-block--*` dans `block_payload()`.

### 3. Contraintes de sécurité, CSP et modération

- **Validation stricte en texte brut** (`apps/blocks/services.py`) : suppression des caractères de contrôle (`CONTROL_RE`), normalisation des espaces (`clean_line`, `clean_paragraphs`), aucun HTML/CSS/JS interprété.
- **URLs et vidéos encadrées** : `clean_https_url()` n'accepte que `https://` (max 300 caractères, sans espace). `parse_video()` n'accepte que YouTube (`YOUTUBE_ID_RE`) et Vimeo (`VIMEO_ID_RE`).
- **CSP stricte & chargement au clic** : les vidéos sont rendues en façade cliquable vers `youtube-nocookie.com` ou `player.vimeo.com` (`dnt=1`). La directive `VIDEO_CSP` (`frame-src`) n'est ajoutée via `apps.core.csp.allow()` que sur les réponses publiques qui contiennent effectivement un bloc vidéo (`has_video`), jamais sur le reste du site.
- **Pipeline images** : toute image passe par `apps.profiles.images.process_image` (vérification du format réel, réencodage WebP, suppression des métadonnées EXIF/géolocalisation, redimensionnement). Les fichiers supprimés sont effacés après validation de la transaction (`_delete_files_on_commit`).
- **Modération & effacement** : un bloc marqué `moderated=True` par l'équipe (`services.moderate` avec trace dans `audit`) n'est jamais rendu (`is_renderable()` retourne `False`) et ne peut plus être modifié par le professionnel. L'admin Django (`PageBlockAdmin`) interdit l'ajout et l'édition du contenu textuel du pro. `delete_all_for_profile()` assure la suppression complète lors du droit à l'effacement.

### 4. Contraintes SEO (`apps/blocks/rendering.py`)

- **Rendu serveur** : `render_map(profile)` prépare les payloads des blocs valides et non modérés, rendus côté serveur par `public/themes/sections/_block.html`.
- **Hiérarchie sémantique** : chaque bloc utilise un `h2` pour son titre et des `h3` pour ses sous-éléments, préservant l'unicité du `h1` de la page.
- **Images responsives** : génération des variantes et attributs `sizes` adaptés (`IMAGE_SIZES`) via `apps.public.responsive.responsive_image`.
- **Données structurées** : `faq_node(payloads, page_url)` produit automatiquement un nœud JSON-LD `FAQPage` fidèle aux questions/réponses affichées des blocs `faq` visibles.
- **Score SEO** : toute modification ou suppression de bloc déclenche `refresh_seo_state(profile)`.

## Alternatives écartées

- **Éditeur HTML / Markdown libre** : risque XSS, rupture de la CSP stricte, dégradation du responsive et de la hiérarchie des titres (`h1`/`h2`).
- **Stocker les blocs directement dans le modèle `ThemeSettings`** : couplage fort avec les thèmes, impossibilité de modérer ou d'indexer finement chaque bloc, gestion complexe des images liées.
- **Iframes vidéo chargées dès le rendu initial** : pénalité sur les Core Web Vitals (LCP/TBT) et requêtes tierces systématiques au chargement de la page.

## Conséquences

- L'ajout d'un nouveau type de bloc est centralisé dans `apps/blocks/registry.py` + son partial `blocks/public/_<kind>.html` (et éditeur si besoin), sans migration de base de données.
- Les garanties de sécurité (CSP, absence de XSS, purge EXIF), de performance et de SEO sont conservées à l'identique sur toutes les pages publiques.

