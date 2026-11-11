# Plateforme Profils Pros & Cartes NFC — Plan complet

> Projet Modulis Tech · plan rédigé le 9 novembre 2026 · version 1.2
> v1.1 : revue architecte (`docs/revues/2026-11-09-revue-plan.md`) · v1.2 : Docker/WSL (ADR-0008), kliz (ADR-0007), OTP par SMS uniquement, équipe d'agents (`.claude/agents/`)
> Sources : *Spécification Plateforme Profils NFC* (3 nov. 2026, F. Choudja) et *Point d'équipe Identité pro numérique* (7 nov. 2026).
> Ce document est la référence. Toute décision qui le modifie passe par un ADR (`docs/adr/`) et une mise à jour ici.

---

## 0. Résumé en 10 lignes

1. Chaque professionnel obtient **gratuitement** une page `domaine.cm/son-nom`, rendue côté serveur, optimisée pour Google.
2. **Un numéro de téléphone vérifié par OTP = un compte = un profil.** C'est la clé anti-doublon.
3. Chaque carte NFC / QR imprimé porte un **identifiant permanent** `domaine/c/K7M2QXP` ; la base décide où il mène.
4. La **page est créée automatiquement** au premier scan d'une carte neuve, à l'inscription web, ou par un agent terrain.
5. Le **SEO est automatique** : titre, description, Open Graph, schema.org, sitemap, canonical, `noindex` des pages trop vides.
6. Stack : **Django 5.2 LTS + PostgreSQL + Huey + HTMX**, rendu serveur, sans framework JS sur les pages publiques.
7. La plateforme est **totalement séparée** du site vitrine Modulis : autre dossier, autre dépôt git, autre domaine, autre déploiement.
8. Versionnage **git local uniquement** (pas de GitHub). Déploiement plus tard par `git push` vers un dépôt nu sur le serveur.
9. Développement en **lots** (0 à 9 pour le MVP), chacun piloté : plan → code → tests → revue par sous-agents → note pédagogique.
10. La **maintenance** (sauvegardes, sécurité, SEO, domaine, stock de cartes) est planifiée dès maintenant (§ 12).

---

## 1. Périmètre et séparation d'avec le site Modulis

| Élément | Site vitrine Modulis (`modulis-site`) | Plateforme Profils (ce projet) |
|---|---|---|
| Dossier | `Desktop/modulis-site (2)` | `Desktop/modulis-profils` |
| Technologie | HTML/CSS/JS statique | Django + PostgreSQL |
| Domaine | domaine de Modulis | **domaine dédié** (à choisir, ex. `xxx.cm`) |
| Dépôt git | indépendant | indépendant (`main` local) |
| Lien entre les deux | un simple lien « Créer ma page pro » depuis la vitrine | un lien « Une solution Modulis Tech » en pied de page |

**Pourquoi un domaine dédié et pas `modulis.cm/profils` ?**
- Les QR imprimés contiennent le domaine : il doit être **court, définitif et indépendant** des refontes du site vitrine.
- Les profils à la racine (`domaine.cm/ange-kenmogne`) sont plus forts en SEO qu'enfouis dans un sous-dossier.
- Une panne ou une refonte du site vitrine ne casse aucune carte.

Rien n'est partagé : ni code, ni base, ni fichiers statiques. Le site vitrine n'est pas modifié par ce projet.

---

## 2. Écarts et ajustements apportés aux documents sources

Lecture croisée des deux PDF : voici les points qu'il faut trancher ou corriger avant de coder. Chacun a un ADR.

| # | Point dans les sources | Problème | Ajustement retenu |
|---|---|---|---|
| A1 | Spécification : « Laravel + MySQL » | Vous privilégiez Django | **Django 5.2 LTS + PostgreSQL** (ADR-0001). Le SEO serveur est aussi bon, et l'admin Django couvre déjà le back-office. |
| A2 | « L'URL de la carte fait une redirection **301** vers le slug » | Le 301 est mémorisé indéfiniment par les navigateurs et les téléphones. Si la carte est perdue, désactivée ou réassociée, ou si le slug change, l'ancien téléphone continue vers l'ancienne cible. | **302** pour `/c/<code>` + `X-Robots-Tag: noindex`. Les **301** sont réservées aux anciens slugs vers le slug actuel (ADR-0003). Côté Google, rien n'est perdu : `/c/` n'est pas une URL à référencer. |
| A3 | Spéc : inscription « téléphone **ou** email » ; Point : « téléphone vérifié = un compte » | Deux clés d'identité = doublons possibles | **Téléphone obligatoire et unique** (format E.164). L'email est facultatif et sert à récupérer le compte (ADR-0004). |
| A4 | Spéc : code carte seul ; Point : code carte **+ code d'activation secret** | Sans secret, quelqu'un qui scanne une carte invendue en boutique peut se l'approprier | Chaque carte a un **code public** (dans le QR) et un **code d'activation** (imprimé sous une zone à gratter ou dans l'emballage), stocké haché (ADR-0005). |
| A5 | Spéc : revenus = cartes seules ; Point : abonnements Essentiel / Pro, offre Équipe, pub | Le modèle de données doit porter les offres dès le départ | Modèle **Plan / Abonnement / Droits** dès le lot 8 ; l'expiration ramène au gratuit, **jamais de suppression**. |
| A6 | Point : « architecture multi-pays dès le départ » | Absent de la spécification | Tables `Country` et `City`, numéros E.164, devise par pays, préfixe de domaine à décider (ADR-0006). Lancement : Cameroun seul. |
| A7 | Pages catégorie `/plombiers/yaounde` à la racine | Risque de collision avec un slug de profil (`/plombiers`) | Liste de **slugs réservés** qui inclut automatiquement tous les métiers, toutes les villes et les routes système. |
| A8 | « Sitemap soumis à Google » | Google a **supprimé l'endpoint de ping** des sitemaps en 2023 | Sitemap déclaré dans `robots.txt` et Search Console ; **IndexNow** pour Bing et Yandex ; l'API Indexing de Google seulement pour les offres d'emploi (JobPosting, V2). |
| A9 | Statistiques : visites et scans | Les robots gonflent les chiffres ; les IP sont des données personnelles | Filtrage des robots, IP **jamais stockées en clair** (hachage salé, renouvelé chaque jour), agrégats journaliers. |
| A10 | Paquet `kliz` (votre demande) | Trouvé sur PyPI (0.3.1) : il ne fait que **notifier** les moteurs (IndexNow + Search Console) | **Adopté pour la notification d'indexation uniquement** (ADR-0007, étude `docs/etudes/kliz.md`). |
| A18 | OTP | Le plan hésitait entre SMS et WhatsApp | **OTP par WhatsApp (API Cloud de Meta, recommandé) ou par SMS (Firebase Authentication)**, passerelle SMS en option ; chaque canal s'active ou se coupe dans le centre de contrôle, les secrets restent dans `.env` (décision du porteur, 10 nov. 2026, ADR-0009 ; remplace « SMS uniquement » du 9 nov.). |
| A19 | Environnement | Le plan v1.1 prévoyait Windows natif sans Docker | **Docker + Compose dans WSL2 Ubuntu**, `Makefile` (ADR-0008). |
| A11 | Outils d'équipe (pre-commit) | Le framework `pre-commit` télécharge ses hooks depuis GitHub | Hooks **git locaux** (`.githooks/`) qui appellent Ruff et les tests installés dans le venv. Zéro dépendance GitHub. |
| A12 | Domaine | « Choix définitif avant toute impression » | Ajout d'une règle de maintenance : **renouvellement automatique sur 5 à 10 ans + alerte**. Un domaine expiré met hors service toutes les cartes vendues. |
| A13 | Domaine `.cm` + multi-pays | Un ccTLD `.cm` est géociblé sur le Cameroun ; or l'URL des cartes est figée à vie | **ADR obligatoire avant le lot 5** : le domaine des cartes doit être court et neutre (sans pays) ; il peut différer du ou des domaines des profils. |
| A14 | Annuaire en V2 seulement | Sans maillage interne, les profils sont des pages orphelines sur un domaine neuf : Google les explore lentement | **Mini-annuaire dès le lot 3** : pages ville, pages métier×ville (seuil ≥ 3), bloc « Autres plombiers à Douala » sur chaque profil, liens depuis l'accueil. |
| A15 | Puces NFC | Une NTAG21x non verrouillée peut être réécrite par n'importe quel téléphone vers une URL de phishing | **Verrouillage définitif** des puces après encodage : critère d'acceptation fournisseur + étape de contrôle du runbook. |
| A16 | « Un utilisateur = un profil » | Bloque un pro qui veut une page personnelle et une page d'entreprise, et ne convient pas à l'offre Équipe | **User 1–N Profile** (nombre limité par l'offre) ; `Card.owner_org` pour qu'une entreprise garde ses cartes au départ d'un salarié. Le téléphone reste l'identité unique du **compte**. |
| A17 | Langue `fr` partout | Le Cameroun est bilingue (régions NO/SO anglophones) | Langue par profil (`fr`/`en`), libellés de métiers bilingues et au féminin (coiffeuse). |

---

## 3. Architecture technique

### 3.1 Choix de la pile (ADR-0001, ADR-0002)

| Couche | Choix | Raison |
|---|---|---|
| Langage | Python 3.13 | Choix prudent : toutes les dépendances le supportent. Python 3.14 est la version la plus récente ; on y passera après vérification de chaque dépendance |
| Framework | **Django 5.2 LTS** | Support de sécurité jusqu'en avril 2028 ; passage à la LTS suivante (6.2) planifié en 2027 |
| Base de données | **PostgreSQL 17** (la 18 existe ; la 17 est éprouvée) | Recherche plein texte, `unaccent` + `pg_trgm` pour l'annuaire, contraintes fiables |
| Tâches de fond | **Huey** (SQLite en dev, Redis en prod), **installé dès le lot 0**, `immediate=True` dans les tests | Léger, fonctionne nativement sous Windows (contrairement à Celery), tâches périodiques incluses |
| Cache | Base de données en dev, **Redis** en prod | Cache des pages publiques, limites de débit |
| Interface d'édition | Templates Django + **HTMX** (`allowEval=false`) + **Alpine.js, version CSP** | Édition fluide sans SPA ; compatible avec une CSP stricte ; pages publiques sans JS bloquant |
| CSS | CSS écrit à la main (variables, mobile d'abord), sans build Node | Pages légères, rien à compiler |
| Images | Pillow → **WebP** + `srcset` | Spéc § Performance |
| QR | `segno` | PNG et SVG, pur Python, sans dépendance système |
| Téléphones | `phonenumbers` | Normalisation E.164, validation par pays |
| Limites de débit | `django-ratelimit` | OTP, activation de cartes, formulaires |
| Configuration | `django-environ` + `.env` | Aucun secret dans git |
| Stockage médias | disque local en dev, S3 compatible en prod (`django-storages`) | Sauvegarde et CDN simples |
| Tests | `pytest`, `pytest-django`, `factory_boy`, `coverage` | Standard professionnel |
| Qualité | `ruff` (lint + format), `django-stubs` + `mypy` (progressif) | |
| Sécurité | `pip-audit`, `check --deploy`, **`django-csp`** (Django 5.2 n'a pas de CSP intégrée, elle arrive en 6.0), **`django-otp`** (double authentification de l'admin), `nh3` (nettoyage du HTML utilisateur) | |
| Anti-robots | Cloudflare **Turnstile** avant tout envoi d'OTP | Empêche la fraude aux SMS |
| SEO local | Lighthouse via `npx` (Node déjà installé), tests automatiques des balises | |

### 3.2 Découpage en applications Django

```
modulis-profils/
├── config/                 réglages (base, dev, test, prod), urls, wsgi/asgi
├── apps/
│   ├── core/               pays, villes, métiers (taxonomie), slugs réservés, utilitaires
│   ├── accounts/           utilisateur personnalisé, téléphone E.164, OTP, sessions
│   ├── profiles/           profil, liens, services, galerie, complétude, historique des slugs
│   ├── public/             page publique, vCard, QR, page d'accueil de la plateforme
│   ├── seo/                métadonnées, JSON-LD, sitemaps, robots.txt, images OG, IndexNow
│   ├── cards/              lots, cartes, codes, activation, liaison, désactivation
│   ├── analytics/          événements (visite, scan, clic), agrégats, filtrage robots
│   ├── moderation/         signalements, file de modération, badge vérifié
│   ├── billing/            offres, abonnements, droits, paiements Mobile Money (fournisseurs)
│   ├── referrals/          parrainage (V1.5)
│   ├── agents/             agents terrain (V1.5)
│   └── directory/          annuaire métier/ville (V2)
├── templates/  static/  locale/
├── tests/                  tests transverses (SEO, parcours complets)
├── docs/                   ce plan, ADR, fiches de lots, runbooks
└── .githooks/              hooks git locaux
```

Règle : une application ne lit jamais directement les tables d'une autre ; elle passe par un module `services.py`. Le code reste ainsi lisible et testable.

### 3.3 Modèle de données (complété par rapport à la spécification)

```
Country(code ISO, nom, indicatif, devise, actif)
City(country, nom, slug, région, lat/lng)
Trade(métier) (nom, slug, pluriel_slug, type_schema_org, segment: artisan|liberal)

User(id, phone_e164 UNIQUE, email nullable, is_staff, date_joined, last_seen, country)
OTPChallenge(phone, code_hmac, but, expire_à, tentatives, ip_hash)

Profile(id, user N–1 (nombre max selon l'offre), organization nullable, display_name, trade, city,
        language: fr|en, bio, photo, kind: person|business, visibility: public|private,
        completeness_score, is_indexable (calculé), verified_at, theme,
        created_by_agent nullable, content_updated_at (≠ updated_at : sert au lastmod),
        status: actif|suspendu|supprimé)
SlugRegistry(slug PK, CHECK slug = lower(slug), kind: current|old|reserved|erased,
             profile nullable, créé_le)
     → UNE seule table pour tous les slugs : l'unicité est garantie par la base, sans course possible.
       current = slug actuel (200), old = ancien slug (301), reserved = routes, métiers, villes,
       erased = profil supprimé (410) : on garde seulement le hachage du slug, pas le nom de la personne.
ProfileLink(profile, type, valeur, ordre)
ProfileService(profile, titre, description, prix_indicatif, ordre)
ProfileMedia(profile, image, texte_alt, ordre)

CardBatch(id, référence, quantité, type: standard|perso|sticker|plaque, fournisseur, créé_par, date)
Card(public_code UNIQUE, activation_code_hash, batch, status, profile nullable,
     owner_org nullable, nfc_locked (contrôle qualité), activated_at, disabled_at, disabled_reason)
     statuts : stock → vendue → activée → désactivée (perdue / remplacée / fraude)

Event(profile, card nullable, type: visit|scan|click_call|click_whatsapp|…,
      date, referer_domain, device, is_bot, visitor_hash)        → partitionnement reporté (non géré par les migrations Django) : index + purge à 13 mois suffisent au début
DailyStat(profile, jour, type, total)                             → agrégat pour les tableaux de bord

Plan(code: free|essentiel|pro|team, prix par pays, droits JSON)
Subscription(profile ou organisation, plan, début, fin, statut)
Payment(référence interne, fournisseur, référence fournisseur, montant, devise, statut, payload brut)
Organization / Membership (offre Équipe, palier 2)

Report(profile, motif, message, statut)                           → modération
Referral(parrain, filleul, statut, récompense)
FieldAgent(user, zone, actif) + AgentCreation(agent, profile, consentement_otp_le)
```

Contraintes clés imposées **dans la base** et pas seulement dans le code :
- `phone_e164` unique ; `SlugRegistry.slug` clé primaire et en minuscules ; `public_code` unique.
- Une carte activée a obligatoirement un profil (contrainte `CHECK`).
- Un profil a plusieurs cartes ; une carte n'a jamais plusieurs profils.
- Créer un métier ou une ville vérifie d'abord le `SlugRegistry` : si un profil occupe déjà ce slug, la création est refusée et signalée à l'admin.

---

## 4. Adresses uniques (URL)

| URL | Rôle | Indexée | Code HTTP |
|---|---|---|---|
| `/` | Accueil de la plateforme (« Crée ta page pro gratuite ») | oui | 200 |
| `/<slug>` | **Page profil publique** | oui si publique et complète | 200 |
| `/<slug>` privé | Profil privé | non | **404** pour les visiteurs (visible par son propriétaire connecté) |
| `/<slug>` suspendu | Fraude ou modération | non | **404**, aucun contenu servi |
| `/<slug>` supprimé | Droit à l'effacement | non | **410** ; ses cartes sont désactivées |
| `/<ancien-slug>` | Ancien slug après renommage | non | **301** → slug actuel (410 si le profil est supprimé) |
| `/c/<CODE>` | Cible du QR / de la puce NFC | non (`noindex`) | **302** → profil, ou page d'activation |
| `/c/<CODE>/activer` | Activation de la carte | non | 200 |
| `/<slug>/contact.vcf` | vCard | non (`X-Robots-Tag`) | 200 |
| `/<slug>/qr.svg`, `/qr.png` | QR du profil (vers `/c/` si une carte existe, sinon vers `/<slug>`) | non (`X-Robots-Tag`) | 200 |
| `/<slug>/og.png` | Image de partage générée (< 300 Ko) | non (`X-Robots-Tag`) | 200 |
| `/villes/<ville>` | Page ville : métiers présents, profils récents (**lot 3**) | oui si ≥ 3 profils indexables | 200 |
| `/espace/…` | Tableau de bord du professionnel | non (`noindex`, connexion requise) | |
| `/sitemap.xml`, `/robots.txt` | SEO | — | |
| `/<metier-pluriel>/<ville>` | Annuaire métier×ville (**version légère au lot 3**, enrichie en V2) | oui si ≥ 3 profils indexables | 200 |

Politique de slash : **pas de slash final** sur les profils (`APPEND_SLASH` ne s'applique pas à eux), redirection 301 de `/slug/` vers `/slug`. Testée automatiquement.
| `/gestion/` | Admin Django (chemin non standard) | non | |

### 4.1 Génération automatique du slug
1. `slugify(unidecode(nom))` → `ange-kenmogne`.
2. S'il est pris ou réservé : on ajoute le métier, puis la ville (`ange-kenmogne-plombier`, `ange-kenmogne-plombier-douala`), puis un suffixe court. On évite `ange-kenmogne-2`, qui a l'air d'un doublon.
3. Longueur 3 à 50 caractères, `[a-z0-9-]`, pas de tiret en début ou en fin, pas de mots interdits.
4. Changement de slug par l'utilisateur : au plus **3 par an**. L'ancien slug passe en `old` dans le `SlugRegistry` et redirige en 301 **pour toujours** ; il ne peut plus être attribué à quelqu'un d'autre.
5. Anti-accaparement : un profil sous le seuil d'indexation ne peut pas choisir un slug « générique » (un seul mot, un nom de métier, de ville ou de marque).

### 4.2 Slugs réservés
Les routes système (`c`, `espace`, `gestion`, `api`, `static`, `media`, `sitemap`, `connexion`, `inscription`, `aide`, `tarifs`, `cgu`…), **plus tous les slugs de métiers et de villes**, plus une liste de marques et de mots sensibles. La liste est vérifiée par un test automatique : toute nouvelle route qui collisionne fait échouer les tests.

### 4.3 Codes de carte
- Alphabet sans caractères ambigus : `23456789ABCDEFGHJKMNPQRSTVWXYZ` (pas de `0/O`, `1/I/L`, `U`) : **30 symboles**.
- **7 caractères** → 30⁷ ≈ 21,9 milliards de combinaisons. Générés avec `secrets`, unicité garantie par la base.
- Comparaison **insensible à la casse** (`/c/k7m2qxp` = `/c/K7M2QXP`) ; la règle « URL en minuscules » ne s'applique pas à `/c/`.
- Code d'activation : 8 caractères, stocké **haché**. Limite par **couple (carte, IP)** : 5 essais par heure. Un seuil global par carte déclenche une alerte, pas un blocage, sinon un tiers qui connaît le code public pourrait bloquer le vrai propriétaire.
- Énumération : `/c/` est limité en débit par IP ; une IP qui teste beaucoup de codes inconnus est bloquée temporairement.
- Puces NFC **verrouillées en écriture** après encodage (contrôle sur échantillon à chaque lot reçu).
- Le format d'URL imprimée est figé à vie : `https://DOMAINE/c/XXXXXXX`. Un test le garantit.

---

## 5. Parcours clés

### 5.1 Création automatique de page — trois entrées, une seule logique

```
Entrée A : inscription web      ┐
Entrée B : premier scan carte   ├──► service unique  profiles.services.get_or_create_profile(phone_vérifié, données)
Entrée C : agent terrain        ┘         │
                                          ├─ téléphone déjà connu → on retourne le profil existant (jamais de doublon)
                                          └─ sinon → création User + Profile (slug auto, ville, métier) + événement
```

Une **page minimale est en ligne immédiatement**, mais reste en `noindex` tant que le score de complétude n'atteint pas le seuil (§ 6.6). Le professionnel voit une jauge « Ta page est prête pour Google à 60 % ». C'est un levier d'engagement.

### 5.2 Scan d'une carte (`/c/<CODE>`)

```
code inconnu                → 404 avec message clair + lien d'aide
carte désactivée            → page « Carte désactivée » + lien vers le profil si encore public
carte en stock ou vendue    → page d'activation :
      1. saisie du code d'activation (vérifié AVANT tout envoi de SMS) + défi Turnstile
      2. saisie du numéro → OTP
      3. compte existant ? → « Associer cette carte à mon profil » (ou choisir lequel de ses profils)
         sinon            → création automatique (5.1, entrée B) → mini-assistant (nom, métier, ville, photo)
      4. carte → statut activée, liée au profil
carte activée               → événement « scan » + 302 vers /<slug>
                              (profil privé → page de contact minimale en noindex, car le porteur de la carte
                               l'a tendue volontairement ; profil suspendu → page « indisponible »)
```

### 5.3 Cycle de vie de l'abonnement
Gratuit → Essentiel → Pro. À l'expiration, retour au gratuit : les **droits** se désactivent (badge, statistiques avancées, retrait du logo Modulis), le **contenu** reste et l'URL et les cartes continuent de fonctionner. Rappels J-30, J-7 et J0 par SMS ou WhatsApp.

---

## 6. SEO automatique — maîtrise complète

Objectif (spécification) : « nom + métier » ou « métier + ville » sur Google mène à une page de la plateforme.

### 6.1 Rendu serveur
Le HTML complet est produit par Django. Aucun contenu important n'est injecté en JavaScript. HTMX n'est utilisé que dans l'espace privé.

### 6.2 Balises générées pour chaque profil
| Balise | Règle |
|---|---|
| `<title>` | `Nom – Métier à Ville` (≤ 60 caractères, on tronque proprement le nom en premier) |
| `meta description` | 150 à 160 caractères : bio nettoyée ; à défaut, gabarit « Nom, métier à Ville. Services : … Contact WhatsApp. » |
| `link rel=canonical` | URL absolue `https://domaine/slug`, toujours sans paramètres |
| `meta robots` | `index,follow` seulement si public **et** indexable (§ 6.6) ; sinon `noindex,follow`. Les profils privés, suspendus ou supprimés ne servent pas de contenu (404/410). |
| Open Graph / Twitter | `og:title`, `og:description`, `og:image` (1200×630 générée), `og:url`, `og:type=profile` ; la carte WhatsApp doit s'afficher correctement |
| `html lang` | langue du profil (`fr` ou `en`) |
| Liens sortants | `rel="ugc nofollow"` sur les profils gratuits (évite que des spammeurs créent des profils pour obtenir des liens) ; schémas autorisés : `https:`, `tel:`, `mailto:`, `wa.me` uniquement |
| `h1` | nom affiché ; `h2` métier et ville |
| Images | `alt` généré (« Réalisation de Nom, plombier à Douala »), dimensions explicites, `loading=lazy` sauf la photo principale |

### 6.3 Données structurées (JSON-LD)
- `Person` (professions libérales) avec `jobTitle`, `address`, `sameAs` (réseaux sociaux), `image`, `url`.
- `LocalBusiness` ou un **sous-type précis** selon le métier (`Plumber`, `HairSalon`, `Electrician`, `AutoRepair`, `Restaurant`…) : la table `Trade` porte ce type.
- `BreadcrumbList` (Accueil › Ville › Métier › Nom) dès le lot 3. Google ne l'affiche plus sur mobile depuis 2025, mais le balisage reste valide et utile sur ordinateur.
- **Échappement** : le JSON-LD est construit à partir de données saisies par les utilisateurs. `<`, `>` et `&` sont échappés en `<`… ; un test injecte `</script>` dans une bio pour le vérifier.
- `AggregateRating` **uniquement** quand les avis sont réels, vérifiés et visibles sur la page (V2). À vérifier avant la V2 : la règle Google sur les avis « auto-promotionnels », puisque le professionnel contrôle sa propre page.
- `JobPosting` pour les offres d'emploi (perspective du Point d'équipe).
- Validation : test automatique du JSON-LD, plus vérification manuelle avec le test des résultats enrichis de Google à chaque lot SEO.

### 6.4 Sitemaps
- Index `sitemap.xml` → `sitemap-profils-1.xml…` (50 000 URL max par fichier), `sitemap-annuaire.xml`, `sitemap-pages.xml`.
- Seules les pages **indexables** y figurent, avec un `lastmod` exact (`content_updated_at` : une mise à jour des statistiques ne le modifie pas).
- Régénération par tâche Huey à chaque modification significative, avec anti-rebond de 10 minutes, et servie depuis le cache.
- Déclaré dans `robots.txt` et dans Google Search Console ; **IndexNow** pour Bing.

### 6.5 robots.txt
Autorise les profils et l'annuaire ; bloque `/espace/` et `/gestion/` ; déclare le sitemap. On **ne bloque pas** les paramètres (`?page=2`, `?utm_…`, `?fbclid=…`) : la balise canonical s'en charge, alors qu'un blocage empêcherait Google de la lire. `/c/` n'est pas bloqué non plus : Google doit pouvoir voir le `noindex`.
En préproduction : **protection par mot de passe seule** (un `Disallow` empêcherait Google de voir le `noindex`). Un test vérifie que le `robots.txt` de production n'est jamais `Disallow: /`.

### 6.6 Score de complétude (anti-pages vides)
| Critère | Points |
|---|---|
| Photo | 20 |
| Métier + ville | 20 |
| Bio ≥ 120 caractères | 20 |
| ≥ 2 services | 15 |
| ≥ 1 moyen de contact (WhatsApp/appel) | 15 |
| ≥ 3 photos de galerie ou ≥ 2 liens | 10 |

Indexable si **toutes** ces conditions sont remplies :
1. page publique et active ;
2. **score ≥ 70** ;
3. **conditions obligatoires**, indépendantes du score : bio d'au moins 120 caractères **et** au moins 60 mots de texte propre au profil (bio + services) ;
4. **bio non dupliquée** : une empreinte (simhash) détecte les bios copiées-collées d'un profil à l'autre, fréquentes avec les agents terrain. Une bio dupliquée met le profil en `noindex` et le signale en modération.

Sans la condition 3, un profil avec photo + métier + 2 services + contact atteindrait 70 sans aucun texte propre : des milliers de pages quasi identiques. Les seuils sont des réglages, et leur effet se mesure dans Search Console.

### 6.7 Performance (Core Web Vitals)
- Objectifs sur mobile 4G moyenne : **LCP < 2,5 s, CLS < 0,1, INP < 200 ms**, page profil **< 150 Ko** hors photos.
- CSS critique en ligne, pas de police web bloquante (police système ou une seule police en `swap`), aucun script tiers sur les pages publiques.
- Images WebP en 3 tailles + `srcset` ; photo principale préchargée.
- Cache des pages publiques (invalidé à l'enregistrement) + CDN (Cloudflare) en production, avec `Cache-Control` adapté.
- **Conséquences du cache**, traitées dès la conception :
  - les visites servies par le CDN n'arrivent pas à Django : on les compte avec un **pixel** (`/p/<id>.gif`, sans cache) ou par lecture des journaux ;
  - le HTML mis en cache ne contient **ni jeton CSRF, ni interface réservée au propriétaire** ;
  - derrière Cloudflare, les limites de débit lisent l'IP réelle dans `CF-Connecting-IP`, en ne faisant confiance qu'aux plages d'IP Cloudflare.
- Lighthouse lancé localement à chaque lot qui touche les pages publiques (score SEO = 100, performance ≥ 90).

### 6.8 Hygiène technique
Un seul hôte canonique (redirection de `www` vers la racine, ou l'inverse), HTTPS forcé, slash final cohérent, URL en minuscules, vraie 404 (pas de « soft 404 »), page 410 pour les profils supprimés à la demande (droit à l'effacement), `hreflang` le jour où plusieurs langues ou pays coexistent.

### 6.9 Maillage interne et pages annuaire (version légère au lot 3, complète en V2)
Sur un domaine neuf, une page qui n'est atteinte que par le sitemap (« page orpheline ») est explorée lentement. Dès le lot 3 :
- l'accueil liste les villes et les métiers actifs ;
- les pages `/villes/<ville>` et `/<metier-pluriel>/<ville>` sont publiées dès le seuil atteint ;
- chaque profil affiche un bloc « Autres plombiers à Douala » (3 à 6 liens) et son fil d'Ariane.

En V2, `/plombiers/douala` reçoit un texte d'introduction unique par combinaison, liste paginée (`?page=2` → canonical vers elle-même, pas vers la page 1), maillage interne vers les villes et métiers voisins. **Publiée seulement si ≥ 3 profils indexables**, sinon `noindex`. Cela évite des milliers de pages vides.

### 6.10 Croissance (Point d'équipe, § 2)
Bandeau « Crée ta page pro gratuite » sur chaque page gratuite (lien interne, et non `nofollow`), bouton de partage WhatsApp avec texte prérempli, parrainage, agents terrain. Chaque profil indexé renforce le domaine.

---

## 7. Sécurité, abus et données personnelles

- **OTP** : 6 chiffres, valable 5 minutes, stocké en **HMAC avec un secret serveur** (un simple hachage d'un code à 6 chiffres se casse en quelques secondes), 5 essais par défi **et** un plafond d'essais par numéro sur l'ensemble des défis, délai progressif. Canaux derrière une interface (`apps/accounts/otp/`, ADR-0009) : **WhatsApp** (API Cloud, modèle d'authentification avec bouton « copier le code »), **SMS via Firebase** (vérifié côté navigateur par Firebase, puis jeton d'identité vérifié par notre serveur : RS256, `aud`, `iss`, fraîcheur, fournisseur « phone », même numéro qu'un défi en attente), **passerelle SMS** en option. Les mêmes règles (indicatifs, plafonds, comptes équipe, numéros bloqués, interrupteurs inscriptions/connexion) s'appliquent à tous les canaux, avant tout envoi.
- **Fraude aux SMS** (« SMS pumping » : des robots font envoyer des SMS vers des numéros surtaxés) : au lancement, seul l'indicatif **+237** est accepté ; défi Turnstile avant l'envoi ; plafonds par numéro, par IP, par préfixe et **plafond de dépense quotidien global** ; alerte si le taux de conversion des OTP chute.
- **Numéros recyclés** : les opérateurs réattribuent les numéros inactifs, et le nouveau titulaire passe l'OTP. Sur un compte inactif depuis plus de 6 mois, ou qui se connecte depuis un nouvel appareil, on demande une vérification supplémentaire (lien envoyé à l'email s'il existe, sinon revue manuelle), et le propriétaire est notifié.
- **Contenu utilisateur** : échappement automatique des templates, aucune bio en HTML brut (texte seul, ou Markdown restreint nettoyé par `nh3`), schémas de liens filtrés (§ 6.2).
- **Activation des cartes** : code secret haché, limite de débit, journal des tentatives, alerte au-delà d'un seuil.
- **Arnaques** (Point d'équipe § 6) : badge vérifié (contrôle manuel ou pièce justificative en V2), bouton « Signaler » sur chaque profil, file de modération, suspension en un clic, filtre de mots-clés à la création.
- **Django** : `SECURE_*`, HSTS, cookies `Secure`/`HttpOnly`/`SameSite`, CSP stricte, admin sur un chemin non standard avec double authentification pour le personnel, `check --deploy` sans avertissement.
- **Fichiers envoyés** : vérification du type réel, réencodage par Pillow (supprime les métadonnées EXIF et la géolocalisation), taille maximale.
- **Données personnelles** : le Cameroun a adopté une loi sur la protection des données personnelles (loi n° 2024/017, à faire confirmer par un juriste). Concrètement : CGU et politique de confidentialité, consentement, droit d'accès et d'effacement (export + suppression), IP hachées, durée de conservation des événements bruts = 13 mois.
- **Secrets** : `.env` jamais versionné ; `.env.example` versionné.

---

## 8. Paiements Mobile Money (lot 8)

- Interface unique `PaymentProvider` (`initier`, `vérifier`, `traiter_webhook`) et un adaptateur par fournisseur. Candidats à comparer : CinetPay, Notch Pay, Campay, Monetbil, Flutterwave, Kora… ainsi que **« Kliz » si vous me donnez son lien** (Q1).
- Paiement annuel d'avance (Point d'équipe). Prix stockés **par pays et par devise**.
- Webhooks : signature vérifiée, **idempotence** (un même événement traité deux fois ne crédite qu'une fois), statut toujours revérifié auprès de l'API avant d'activer un droit.
- Rapprochement quotidien automatique entre les paiements locaux et ceux du fournisseur.

---

## 9. Feuille de route de développement (lots)

Chaque lot a sa fiche dans `docs/lots/`. Un lot n'est terminé que lorsque sa **définition de « terminé »** (§ 10.4) est remplie.

### MVP — Phase 1 et 2 de la spécification, palier 1 du Point d'équipe

| Lot | Contenu | Livrable vérifiable |
|---|---|---|
| **0. Fondations** | Installer Python 3.13 et PostgreSQL 17 ; squelette Django ; réglages dev/test/prod ; `.env` ; Ruff ; pytest ; **Huey** ; hooks git locaux ; vérification locale (`scripts/check.ps1`) ; **sauvegarde du dépôt** (`git bundle` quotidien vers un disque externe) ; page « hello » | `check.ps1` passe, 1 test vert, premier commit, premier bundle |
| **1. Comptes & OTP** | Utilisateur personnalisé (téléphone E.164), OTP, limites de débit, fournisseur SMS factice en dev | Inscription et connexion par OTP de bout en bout |
| **2. Profils & création auto** | Modèles, slug auto + réservés + historique, service `get_or_create_profile`, assistant de création, éditeur HTMX, galerie WebP | Une page `/slug` est créée et éditable |
| **3. Page publique & SEO** | Gabarit public mobile d'abord, balises, JSON-LD, OG image, canonical, robots, sitemap, complétude + détection des bios dupliquées, 404/410, **mini-annuaire** (pages ville, métier×ville, bloc « autres pros », fil d'Ariane) | Tests SEO verts + Lighthouse SEO 100 |
| **4. vCard & QR** | vCard 3.0 (compatibilité iOS/Android), QR PNG/SVG, bouton partager WhatsApp | Contact ajouté sur un vrai téléphone |
| **5. Cartes NFC** | **Prérequis : ADR du domaine des cartes accepté et domaine acheté.** Lots, génération de codes, export CSV/PDF pour l'imprimeur, `/c/<code>`, activation, liaison, remplacement d'une carte perdue, contrôle du verrouillage NFC | Parcours 5.2 testé sur une vraie carte NFC, puce verrouillée |
| **6. Statistiques** | Événements, filtrage des robots, agrégats quotidiens, tableau de bord | Chiffres justes sur un scénario de test |
| **7. Back-office & modération** | Admin Django personnalisé : lots, activations, signalements, suspension, badge vérifié | Un modérateur traite un signalement |
| **8. Offres & paiement** | Plans, droits, abonnements, fournisseur Mobile Money (bac à sable), rappels | Paiement test → droits Essentiel actifs → expiration → retour gratuit |
| **9. Durcissement & préproduction** | Sécurité, performance, sauvegardes, journalisation, serveur de préproduction, runbooks | `check --deploy` propre, restauration de sauvegarde testée |

### Après le MVP
| Version | Contenu |
|---|---|
| V1.5 (palier 1→2) | Parrainage (3 inscrits = 1 mois Essentiel, comptés seulement après activation réelle), espace agents terrain, rapport WhatsApp mensuel, procédure de **réclamation de profil** (usurpation, mauvais numéro saisi par un agent) |

**Agents terrain : règles de sécurité.**
- Le consentement du professionnel passe par un **jeton de consentement dédié** envoyé par SMS (« J'accepte que X crée ma page »). Ce n'est pas un code de connexion : l'agent n'obtient jamais de session sur le compte.
- Rémunération à l'activation ou selon la qualité du profil, jamais au simple nombre de créations.
- Détection des doublons sur nom + métier + ville.
| V2 (palier 2) | Offre Équipe (organisation + membres + gestion centrale des cartes), cartes personnalisées, kits vitrine |
| V2 (palier 3) | Annuaire métier/ville, avis clients vérifiés, mise en avant payante, thèmes |
| V3 (palier 4) | Devis, rendez-vous, catalogue, paiement client par Mobile Money, offres d'emploi (JobPosting) |
| V3+ | Multi-pays (CI, SN, GA), publication sur les réseaux sociaux, intégration BâtiVitrine |

---

## 10. Méthode de travail : codage assisté, supervisé par agents

### 10.1 Les rôles
| Rôle | Qui | Responsabilité |
|---|---|---|
| Porteur produit / décideur | **Vous** | Valide les fiches de lot, tranche les questions ouvertes, teste sur téléphone |
| Chef de projet technique / superviseur | **Claude (session principale)** | Découpe, délègue, relit tout ce que les agents produisent, intègre, commit, vous explique |
| Architecte | sous-agent `Plan` | Plan détaillé de chaque lot avant tout code |
| Développeurs | sous-agents `general-purpose` (en worktree git isolé quand des tâches sont parallèles) | Implémentent une tâche précise avec ses tests |
| Relecteur | `/code-review` + sous-agent relecteur | Bugs, lisibilité, respect des conventions |
| Auditeur sécurité | `/security-review` | À chaque lot qui touche à l'authentification, aux cartes ou aux paiements |
| Auditeur SEO | sous-agent dédié (liste de contrôle § 6) | À chaque lot qui touche les pages publiques |
| Explorateur | sous-agent `Explore` | Recherches dans le code quand il grossit |

### 10.2 Le cycle d'un lot
```
1. Fiche de lot (docs/lots/LOT-xx.md) : objectif, tâches, critères d'acceptation  → validation par vous
2. Plan technique (agent Plan) → relu par le superviseur
3. Branche locale  feature/lot-xx-nom
4. Implémentation par tâches (agents développeurs) — tests écrits en même temps
5. scripts/check.ps1 : ruff + tests + couverture + check Django
6. Revue (code-review, sécurité et/ou SEO selon le lot) → corrections
7. Démonstration : runserver + navigateur intégré, vérification sur mobile
8. Note pédagogique « Ce qu'on a appris » ajoutée à la fiche
9. Fusion  git merge --no-ff  dans main + tag (v0.x.0) — sur votre feu vert
```

### 10.3 Conventions git (local uniquement)
- `main` toujours stable ; une branche par lot ; commits au format **Conventional Commits** (`feat(cards): activation par code secret`).
- Tags de version `v0.1.0` … `v1.0.0` (MVP).
- Pas de dépôt distant en ligne. **Dès le lot 0**, un `git bundle` quotidien (ou un dépôt nu) est copié sur un disque externe ou une clé USB : sans cela, le portable est l'unique copie. Plus tard : dépôt nu sur le serveur (`git push prod main`).
- Hooks dans `.githooks/` (`git config core.hooksPath .githooks`). Ils s'exécutent avec le `sh` de Git Bash et appellent `.venv/Scripts/python.exe` :
  - `pre-commit` = Ruff + tests rapides ;
  - `pre-merge-commit` = suite complète.
  
  Il n'y a pas de remote, donc un hook `pre-push` ne se déclencherait jamais.
- Pas de `make` sous Windows : un seul point d'entrée, `scripts/check.ps1` (au besoin `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`).

### 10.4 Définition de « terminé » (chaque tâche)
- [ ] Code formaté et sans erreur Ruff
- [ ] Tests écrits et verts ; couverture ≥ 85 % sur les services métiers
- [ ] Migrations créées, relues, réversibles
- [ ] Aucun secret ni donnée réelle dans git
- [ ] Revue faite, retours traités
- [ ] Vérifié dans le navigateur (et sur téléphone si c'est une page publique)
- [ ] Documentation et fiche de lot mises à jour

### 10.5 Apprendre en même temps
Chaque lot se termine par une note courte : concepts Django vus (ORM, migrations, vues, formulaires, middleware, signaux, cache…), pièges rencontrés, commandes utiles. Le glossaire est dans `docs/apprendre/`.

---

## 11. Environnements

| Env. | Où | Base | Particularités |
|---|---|---|---|
| dev | votre PC Windows | PostgreSQL local | `DEBUG=True`, SMS et paiement factices, Huey SQLite |
| test | pytest | PostgreSQL (base de test) | données générées par `factory_boy` |
| préprod | VPS (plus tard) | PostgreSQL | `noindex` + mot de passe, fournisseur de paiement en bac à sable |
| prod | VPS + Cloudflare | PostgreSQL + Redis | Nginx + Gunicorn, HTTPS, sauvegardes |

**Poste de développement** (ADR-0008) : Windows 11 + WSL2 Ubuntu 26.04 (Python 3.14 pour le venv de tests) + Docker Engine dans WSL (`scripts/wsl/install-docker.sh`). PostgreSQL et Redis tournent dans Docker : rien à installer sous Windows.

---

## 12. Plan de maintenance

### 12.1 Calendrier
| Fréquence | Tâche | Outil |
|---|---|---|
| Continu | Surveillance de disponibilité (page profil + `/c/` test) | Uptime Kuma (auto-hébergé) ou service équivalent |
| Continu | Erreurs applicatives | journaux + GlitchTip (compatible Sentry, auto-hébergeable) |
| Quotidien | Sauvegarde PostgreSQL + médias, chiffrée, hors serveur, rétention 7 j / 4 sem. / 12 mois | `pg_dump` + `restic` |
| Quotidien | Rapprochement des paiements, agrégation des statistiques, purge des OTP expirés | tâches Huey |
| Hebdo | Search Console : couverture, erreurs d'indexation, Core Web Vitals, requêtes | — |
| Hebdo | File de modération et signalements | admin |
| Mensuel | Mises à jour de sécurité Django et dépendances, `pip-audit`, tests complets | — |
| Mensuel | **Test de restauration** d'une sauvegarde sur une base vide | runbook |
| Mensuel | Stock de cartes : vendues / activées / anomalies d'activation | admin |
| Trimestriel | Audit SEO complet (crawl, liens cassés, pages minces, sitemap vs index) | Screaming Frog (gratuit ≤ 500 URL) ou script maison |
| Trimestriel | Revue de performance (Lighthouse, requêtes lentes, taille de la base) | — |
| Annuel | **Domaine** : vérifier le renouvellement automatique (5 à 10 ans d'avance), DNS, certificats | — |
| Continu | Dépense SMS et taux de délivrance et de conversion des OTP (alerte en cas d'anomalie) | tableau de bord + alerte |
| Continu | **Battement de cœur** des tâches périodiques : alerte si une tâche Huey ne s'est pas exécutée (sitemaps, expirations d'abonnement, agrégats) | Uptime Kuma (push) |
| Hebdo | Search Console : part « Explorée, actuellement non indexée » (signal de pages jugées trop pauvres) | — |
| Après chaque lot imprimé | Vérifier que l'export contenant les codes d'activation a été supprimé ; contrôler le verrouillage NFC sur échantillon | runbook |
| Quotidien | Copie du dépôt git (`git bundle`) sur support externe | script |
| Avril 2028 | Fin de support de Django 5.2 → migrer vers la LTS suivante **courant 2027** | ADR dédié |

### 12.2 Runbooks à écrire (lot 9)
Restaurer une sauvegarde · remplacer une carte perdue · réclamation ou litige sur un profil · numéro de téléphone recyclé · recevoir et contrôler un lot de cartes · suspendre un profil frauduleux · rembourser ou corriger un paiement · migrer de serveur · le domaine ne répond plus · pic de trafic · fuite de données (procédure de notification).

### 12.3 Indicateurs suivis (paliers du Point d'équipe)
Profils créés, profils indexables, % de profils complets, cartes activées / vendues, payants, taux de renouvellement, % du trafic venant de Google. Ce sont les seuils de passage de palier (1 000 profils / 100 payants…).

---

## 13. Risques

| Risque | Impact | Parade |
|---|---|---|
| Changement de domaine après impression | Toutes les cartes sont mortes | Domaine choisi et payé pour plusieurs années **avant** le lot 5 ; format d'URL figé par un test |
| Pages vides indexées | Domaine dévalorisé | Seuil de complétude + `noindex` + annuaire ≥ 3 profils |
| Usurpation de carte invendue | Litiges | Code d'activation secret, vérifié avant l'OTP |
| Puce NFC réécrite par un tiers vers du phishing | Réputation, sécurité des clients | Verrouillage en écriture obligatoire |
| Fraude aux SMS (SMS pumping) | Facture SMS qui explose | +237 seul, Turnstile, plafonds de dépense |
| Numéro recyclé par l'opérateur | Prise de contrôle d'un compte | Vérification supplémentaire sur les comptes inactifs |
| Profils orphelins sur un domaine neuf | Indexation lente | Mini-annuaire et maillage dès le lot 3 |
| Faux profils et arnaques | Réputation | Vérification, signalement, modération dès la V1 |
| Coût et fiabilité des SMS OTP | Inscriptions bloquées | Deux fournisseurs (SMS + WhatsApp) derrière une interface ; repli |
| Fournisseur de paiement indisponible | Pas de revenu | Interface multi-fournisseurs, rapprochement quotidien |
| Perte de données | Fatal | Sauvegardes testées chaque mois |
| Dette technique | Lenteur à long terme | Revue systématique, tests, ADR |

---

## 14. Questions ouvertes (à trancher par vous)

| # | Question | Bloque |
|---|---|---|
| ~~Q1~~ | ~~« Kliz »~~ → **résolu** : paquet Python d'indexation, adopté (ADR-0007) | — |
| Q2 | Nom et domaine définitifs (ModulisCard, Tapo, MonPro, KartPro…). Le domaine **des cartes** doit être neutre (sans pays) à cause de l'expansion prévue ; ADR à écrire | lot 5 (impression) — le dev peut commencer avant |
| Q3 | Fournisseurs OTP (ADR-0009) : **WhatsApp Cloud API** (créer l'app Meta, le numéro expéditeur et faire approuver le modèle d'authentification) et **Firebase Authentication** (projet, fournisseur « Téléphone », domaines autorisés, région SMS limitée au Cameroun). Agrégateur SMS local facultatif (backend dans `apps/accounts/sms.py`) | mise en ligne |
| Q4 | Fournisseur Mobile Money | lot 8 |
| Q5 | Fournisseur des cartes NFC (puce NTAG213/215/216, quantité, délai) | lot 5 |
| Q6 | Hébergeur du VPS (Hetzner, OVH, Contabo…) | lot 9 |
| Q7 | Lien avec BâtiVitrine : produit commun ou séparé | V3 |
| Q8 | Seuil de complétude (70 proposé) et nombre de changements de slug par an (3 proposé) | lot 3 |
