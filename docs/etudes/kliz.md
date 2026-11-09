# Étude du paquet `kliz` — ce qu'il vaut pour notre besoin

> Étude du 9 novembre 2026, faite sur le **code source réel** de `kliz 0.3.1` (PyPI, 8 octobre 2026, licence MIT,
> auteur Freddy Choudja), installé dans le venv WSL et lu fichier par fichier.

## 1. Ce que fait kliz

`kliz` **prévient les moteurs de recherche** qu'une page a été créée, modifiée ou supprimée. Rien de plus.

| Fournisseur | Moteurs touchés | Mécanisme | Pages concernées |
|---|---|---|---|
| `IndexNowProvider` | Bing, Yahoo, DuckDuckGo, Ecosia, Copilot, Yandex, Naver, Seznam, Yep | POST JSON vers `api.indexnow.org` (jusqu'à 10 000 URL par requête) | toutes |
| `GoogleSearchConsoleProvider` | Google | **Renvoie le sitemap** via l'API Search Console (compte de service) | toutes |
| `GoogleProvider` | Google | Indexing API | **uniquement JobPosting et BroadcastEvent** (règle Google) |

Il fournit aussi `read_sitemap` (index, `.gz`, filtre `--since`), `normalize_url`, une CLI et une GitHub Action.

## 2. Qualité du code (lecture de `core.py`, `providers/indexnow.py`, `_validation.py`)

Points forts, vérifiés dans le code :
- **Robustesse par lot** : les URL invalides ou d'un autre hôte sont rejetées individuellement, et le lot continue (`_group_by_host`).
- **Nouvelles tentatives sérieuses** : backoff exponentiel avec gigue, respect de `Retry-After`, plafond `max_delay` et budget `deadline`. Désactivées par défaut (`max_attempts=1`), ce qui est un choix sain.
- **Clé IndexNow masquée** dans les messages et les journaux (`_redact`) ; `verify_key` détecte le piège classique : un site qui répond 200 avec une page HTML pour un fichier absent.
- **Validation d'URL** : rejet des fragments, des identifiants dans l'URL et des schémas non HTTP ; IDN converties en punycode.
- **XML lu avec `defusedxml`** (protégé contre les attaques XML).
- **Crochets d'observation** `on_result` / `on_retry`, qui permettent de journaliser chaque résultat en base.
- Typé (`py.typed`), 2 dépendances seulement (`requests`, `defusedxml`) ; les dépendances Google sont optionnelles.

Limites :
- **Synchrone** (`requests`) : il ne faut jamais l'appeler dans une requête web. Il doit tourner dans une tâche de fond (Huey chez nous).
- **Ce n'est pas un outil SEO complet** : il ne génère ni balises, ni JSON-LD, ni sitemap, ni maillage. Il ne fait que la notification, c'est-à-dire l'étape 8 sur 9 de notre chaîne SEO.
- Côté Google, il ne peut que **renvoyer le sitemap** ; ce n'est pas une demande d'indexation page par page (Google n'en propose plus pour les pages ordinaires).
- Version 0.x (bêta) : il faut épingler la version exacte et relire le changelog avant chaque mise à jour.
- Sa GitHub Action ne nous sert pas (pas de GitHub) : on utilise uniquement la bibliothèque Python.

## 3. Verdict

**Adopté, pour la partie « notification d'indexation » uniquement.** Il remplace utilement ~300 lignes que nous aurions
écrites nous-mêmes (protocole IndexNow, nouvelles tentatives, vérification de clé, lecture de sitemap) avec une qualité
supérieure à une première version maison. Le reste du SEO (balises, JSON-LD, sitemaps, `robots.txt`, complétude,
maillage) reste dans notre application `apps/seo`.

## 4. Aller plus loin : notre intégration `apps/seo/indexing`

Ce que nous ajoutons autour de kliz :

| Besoin | Notre solution |
|---|---|
| Ne jamais bloquer une requête web | Tâche Huey `notify_indexing` |
| Éviter de spammer les moteurs quand un pro enregistre 10 fois de suite | **Anti-rebond** : file `IndexingQueue` (URL unique), vidée toutes les 10 minutes en un seul lot |
| Prévenir aussi des **suppressions** (profil passé en privé, suspendu, supprimé ou sous le seuil) | Les URL qui répondent désormais 404/410 sont envoyées à IndexNow, comme le protocole le prévoit |
| Ne notifier que ce qui compte | Seuls les profils **indexables** (ou qui viennent de cesser de l'être) entrent dans la file ; les simples mises à jour de statistiques n'y entrent pas |
| Servir la clé IndexNow | Vue Django `/<clé>.txt` (texte brut, HTTP 200, sans redirection), et commande `manage.py indexnow_verify` qui appelle `verify_key` |
| Historique et supervision | Crochet `on_result` → table `IndexingLog`, visible dans l'admin (taux de succès, dernières erreurs) |
| Google | `GoogleSearchConsoleProvider` activé seulement si un compte de service est configuré ; un renvoi du sitemap par jour au maximum, sans surconsommer le quota |
| Rattrapage | Tâche quotidienne : `read_sitemap` + `--since` (pages modifiées depuis 24 h), au cas où une notification aurait échoué |
| Tests | Aucun appel réseau : un faux fournisseur (`BaseProvider`) est injecté dans les tests |
| Environnements | Désactivé en dev et en préproduction (`KLIZ_ENABLED=False`) : on ne notifie jamais les moteurs pour une URL qui n'est pas en production |

## 5. Suggestions à faire remonter à l'auteur (même équipe)

- Un mode asynchrone (`httpx`) ou un module `kliz.contrib.django` (vue de clé, tâche, journal), pour éviter que chaque projet Django réécrive notre intégration.
- Une option pour regrouper les notifications Google (un seul renvoi du sitemap par fenêtre de temps).
