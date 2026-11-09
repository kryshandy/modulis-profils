# ADR-0007 — kliz pour les notifications d'indexation

Statut : Acceptée · 2026-11-09

## Contexte
Le porteur du projet demande d'utiliser le paquet Python `kliz` pour le SEO. L'étude du code source
(`docs/etudes/kliz.md`) montre qu'il ne fait que **notifier** les moteurs (IndexNow, renvoi du sitemap à Search Console,
Indexing API pour les offres d'emploi). Il le fait bien : validation, tentatives multiples, clé masquée, XML sûr.

## Décision
`kliz==0.3.1` (version épinglée) est utilisé uniquement dans `apps/seo` pour la notification, derrière une file
anti-rebond (`IndexingQueue`) vidée par une tâche Huey toutes les 10 minutes. Chaque résultat est journalisé dans
`IndexingLog` via le crochet `on_result`. Il est désactivé hors production (`KLIZ_ENABLED`).
Le reste du SEO (balises, JSON-LD, sitemaps, robots, complétude, maillage) reste développé par nous.

## Alternatives
- Implémentation maison d'IndexNow : environ 300 lignes, moins robuste au départ.
- Ne rien notifier (se contenter du sitemap) : indexation plus lente sur Bing et Yandex, ce qui est dommage pour un domaine neuf.

## Conséquences
Dépendance en version 0.x : relire le changelog avant chaque montée de version. Les tests n'appellent jamais le réseau
(un faux fournisseur est injecté).
