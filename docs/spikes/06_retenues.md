# Spike n°6 — Remplissage des retenues d'eau potable

Date : 2026-09-30 · Département : 85 · Exploration interactive, sans script (requêtes reproductibles ci-dessous)

## Contexte

En Vendée, 94 % de l'eau potable provient de retenues de surface gérées par Vendée Eau (source : vendee-eau.fr). Leur remplissage est l'information la plus suivie localement en période de sécheresse, et elle manque au projet.

## Sources trouvées

| Source | Contenu | Historique | Mise à jour | Accès |
|---|---|---|---|---|
| **Département de la Vendée, ArcGIS Online** (organisation `hxI0sAfc91bJCkko`), table `TABL_2021_01_07_FICHIER_SOURCE_DASHBOARD_BARRAGES_TEST` | **13 retenues**, une ligne par retenue et par semaine : capacité, volume stocké, % de remplissage, coordonnées | **depuis janvier 2019** (5 251 lignes, 52 semaines par an, complet) | hebdomadaire (dernière : semaine 39, au 27/09/2026) | REST ArcGIS public, JSON, pagination par 1 000 |
| Même organisation, table `TABL_2026_01_12_FICHIER_SOURCE_DASHBOARD_HISTORIQUE_BARRAGES` | **volume total** stocké (Mm³), une colonne par année, une ligne par semaine | **depuis 2012** | hebdomadaire | idem |
| DREAL Bretagne, WFS `dreal_b:qry_remplissage_retenues` (GéoBretagne) | 336 retenues en France, dont 15 de Vendée Eau et 26 réserves de substitution du Marais poitevin (SIEMP, EPMP) | **aucun** : seules les données de moins d'une semaine sont exposées | hebdomadaire | WFS public, JSON |
| vendee-eau.fr, « L'état de la ressource » | tableaux récapitulatifs | — | hebdomadaire (le mardi) | **images JPG** uniquement |

Les tables du Département alimentent le tableau de bord « Barrages de Vendée Eau » du hub ArcGIS départemental. Capacité totale des 13 retenues : 55,8 Mm³. Au 27/09/2026 : 35,6 % (de 16,7 % à Pierre-Brune à 49,3 % à Mervent).

Requête type (table par retenue) :

```
https://services-eu1.arcgis.com/hxI0sAfc91bJCkko/arcgis/rest/services/
  TABL_2021_01_07_FICHIER_SOURCE_DASHBOARD_BARRAGES_TEST/FeatureServer/0/query
  ?where=1=1&outFields=*&resultOffset=0&resultRecordCount=1000&orderByFields=ObjectId&f=json
```

## Points d'attention

- **Fragilité** : les noms des services changent d'une année à l'autre (`TABL_2021_…`, `TABL_2025_…`, `TABL_2026_…`), la table à jour porte le suffixe `_TEST`, et l'ensemble est publié par un compte individuel du Département. Aucune licence de réutilisation n'est indiquée. Un contact avec le Département ou Vendée Eau est souhaitable, pour obtenir un flux stable et un accord de réutilisation.
- **Historique court** : 7 ans par retenue et 14 ans en total, sous le minimum de 15 ans de la période de référence. Une standardisation reste fragile, comme pour ONDE (D3).
- **Nature de l'indicateur** : le remplissage résulte des apports naturels, mais aussi des **prélèvements et de la gestion** (réalimentation, transferts). Il mêle l'état de la ressource et la pression de la demande, deux axes que la spec sépare (principe n°3).
- **Généricité** : la source du Département est propre à la Vendée. La couche de la DREAL Bretagne est nationale mais sans historique : en l'archivant chaque semaine, on constituerait un historique pour n'importe quel département.

## Propositions (à valider)

1. **Nouvelle source `retenues`** : un module d'ingestion hebdomadaire, un fichier par année (`data/raw/retenues/retenues_<annee>.parquet`) et un référentiel des retenues dans `stations.parquet` (source `retenue`). C'est une nouvelle source et un changement de schéma : ajout d'une table `obs.retenue_semaine`.
2. **Affichage hors composite en V1**, comme ONDE : courbe de la semaine comparée à l'enveloppe minimum, médiane et maximum 2019–2025 (13 retenues) et 2012–2025 (total). La place naturelle de cet indicateur est l'axe « tension » de la V3.
3. **Connecteur configurable** dans `config/sources.yaml` (service ArcGIS du Département pour la Vendée), avec la couche nationale de la DREAL Bretagne en solution de repli, archivée chaque semaine.
4. **Plus tard (V3)** : les réserves de substitution agricoles du Marais poitevin (SIEMP de l'EPMP), pour l'axe pression.

## Suite (2026-09-30)

Propositions 1 à 3 adoptées (méthodologie, D6) et implémentées : `pipeline/sources/retenues.py`, `pipeline/stockage.py`, 5 239 relevés de 2019 à 2026 dans `data/raw/retenues/`. Deux constats faits à l'implémentation :

- les numéros « Semaine NN » de la source ne suivent pas la norme ISO dans 26 % des cas : on ne lit que la date du relevé ;
- la table du total depuis 2012 est décalée d'une semaine par rapport à la somme des retenues sur une partie des années (écart médian de 0,4 Mm³, jusqu'à 6,8 Mm³) : elle n'est pas ingérée.

Dans la couche nationale, les géométries sont des `MultiPoint`, parfois aberrantes (une latitude de −5,98), et les retenues sans relevé portent des chaînes vides : le connecteur de repli en tient compte.
