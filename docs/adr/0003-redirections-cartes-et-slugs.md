# ADR-0003 — 302 pour les cartes, 301 pour les anciens slugs

Statut : Proposée · 2026-11-09

## Contexte
La spécification prévoit une redirection 301 de `/c/<code>` vers le profil. Or un 301 est « permanent » : navigateurs et
téléphones le mettent en cache sans limite. La cible d'une carte peut pourtant changer (carte perdue puis désactivée,
réassociation, renommage du slug, profil suspendu). Chaque scan doit aussi être compté, ce qu'un 301 en cache empêche.

## Décision
- `/c/<code>` : **302** avec `Cache-Control: no-store` et `X-Robots-Tag: noindex`. Chaque scan arrive au serveur, qui
  enregistre l'événement puis décide.
- `/<ancien-slug>` : **301** vers le slug actuel, pour toujours ; un ancien slug n'est jamais réattribué.
- Profil supprimé (droit à l'effacement) : son slug et ses anciens slugs répondent **410**, ses cartes sont désactivées,
  et le registre ne conserve qu'un hachage du slug (le nom de la personne n'est pas gardé).
- Profil privé ou suspendu : **404** pour les visiteurs.
- Tous les slugs (actuels, anciens, réservés, effacés) vivent dans une seule table `SlugRegistry` : l'unicité est garantie par la base.
- Le QR téléchargeable d'un profil pointe vers `/c/<code>` si une carte est liée, sinon vers `/<slug>`.

## Conséquences
Le SEO n'est pas touché : les URL `/c/` ne sont pas destinées à l'index, et la page canonique reste `/<slug>`.
Les statistiques de scans sont fiables.
