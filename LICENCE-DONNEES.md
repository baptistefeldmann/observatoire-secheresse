# Licence des données

Le **code** de l'observatoire est sous licence MIT (fichier [`LICENSE`](LICENSE)). Les **données** relèvent de deux régimes : celles que l'observatoire produit, sous Licence Ouverte, et celles des fournisseurs, qui gardent leurs propres conditions.

## Données produites par l'observatoire

Sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) (Etalab) : réutilisation libre, y compris commerciale, à condition de citer la source et la date de mise à jour.

| Données | Emplacement |
|---|---|
| Indices hebdomadaires (stations, zones, composite) | `data/indices/`, tables `idx.*`, API, site public |
| Normales de référence, enveloppes, ruptures détectées | `data/normales/` |
| Découpage en zones et rattachement des stations | `data/referentiels/zones.parquet`, `stations.parquet` |

Mention suggérée : « Observatoire de la sécheresse (Vendée), Baptiste Feldmann, d'après Hub'Eau, Météo-France, SANDRE et IGN, méthode D9, données du AAAA-MM-JJ ».

Les indices sont un prototype en cours de validation (voir la feuille de route du README) : leur réutilisation se fait sans garantie d'exactitude.

## Données des fournisseurs

Les données brutes (`data/raw/`) et les fonds de carte restent soumis aux conditions de leur producteur.

| Source | Producteur | Conditions |
|---|---|---|
| Réanalyse SIM (pluie, ETP, humidité du sol) | Météo-France, via data.gouv.fr | Licence Ouverte 2.0 |
| Masses d'eau souterraine, zones d'alerte | SANDRE (OFB) | Licence Ouverte 2.0 (etalab-2.0) |
| Niveaux de nappe, débits, écoulement ONDE | Hub'Eau (BRGM, OFB, Schapi) | conditions de Hub'Eau et des producteurs, à confirmer sur leurs sites |
| Communes, Plan IGN | IGN (Géoplateforme, geo.api.gouv.fr) | conditions de l'IGN, à confirmer sur ses sites |
| **Remplissage des retenues d'eau potable** | Département de la Vendée (table ArcGIS publique) | **aucune licence publiée : non couvert par la Licence Ouverte ci-dessus**. Ces relevés sont affichés à titre d'information et restent la propriété de leur producteur. |
