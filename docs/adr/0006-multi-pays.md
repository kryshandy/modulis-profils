# ADR-0006 — Multi-pays dès le modèle de données

Statut : Proposée · 2026-11-09

## Contexte
Lancement au Cameroun, puis Côte d'Ivoire, Sénégal et Gabon (Point d'équipe). Ajouter la notion de pays après coup
obligerait à migrer toutes les données.

## Décision
Tables `Country` et `City` dès le lot 0 ; chaque utilisateur et chaque profil porte un pays ; prix et devise par pays
(XAF puis XOF) ; numéros en E.164. La stratégie de domaine (un domaine global + préfixe pays, ou un ccTLD par pays) est
décidée plus tard, dans un ADR distinct, **avant l'ouverture du deuxième pays**. Les codes de carte restent globaux et
uniques, quel que soit le pays.

**Domaine des cartes** : comme l'URL imprimée est figée à vie, il doit être court et **neutre** (pas un ccTLD national
comme `.cm`, géociblé sur un seul pays). Un ADR dédié tranche ce point **avant le lot 5**. Le domaine des cartes peut
différer du ou des domaines des profils.

Langue : chaque profil porte sa langue (`fr`/`en`), car le Cameroun est bilingue.

## Conséquences
Peu de coût aujourd'hui (un champ et deux tables), aucune migration douloureuse demain.
