# Licence des données

Le **code** de l'observatoire est sous licence MIT (fichier [`LICENSE`](LICENSE)). Les **données** relèvent de deux régimes : celles que l'observatoire produit, sous Licence Ouverte, et celles des fournisseurs, qui gardent leurs propres conditions.

## Données produites par l'observatoire

Sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) (Etalab) : réutilisation libre, y compris commerciale, à condition de citer la source et la date de mise à jour.

| Données | Emplacement |
|---|---|
| Indices hebdomadaires (stations, zones, composite) | `data/indices/`, tables `idx.*`, API, site public |
| Normales de référence, enveloppes, ruptures détectées | `data/normales/` |
| Découpage en zones et rattachement des stations | `data/referentiels/zones.parquet`, `stations.parquet` |

Mention suggérée : « Observatoire de la sécheresse (Vendée), Baptiste Feldmann, d'après Hub'Eau, Météo-France, SANDRE et IGN, méthode D14, données du AAAA-MM-JJ ».

Les indices sont un prototype en cours de validation (voir la feuille de route du README) : leur réutilisation se fait sans garantie d'exactitude.

## Données des fournisseurs

Les données brutes (`data/raw/`) et les fonds de carte restent soumis aux conditions de leur producteur.

| Source | Producteur | Conditions |
|---|---|---|
| Réanalyse SIM (pluie, ETP, humidité du sol) | Météo-France, via data.gouv.fr | Licence Ouverte 2.0 |
| Masses d'eau souterraine, zones d'alerte | SANDRE (OFB) | Licence Ouverte 2.0 (etalab-2.0) |
| Arrêtés sécheresse (`data/validation/`, validation seulement) | VigiEau (ministère de la Transition écologique), via data.gouv.fr | Licence Ouverte 2.0 |
| Niveaux de nappe, débits, écoulement ONDE | Hub'Eau (BRGM, OFB, Schapi) | Licence Ouverte Etalab (vérifié le 2026-10-23) : « les Jeux de données sont librement et gratuitement utilisables et réutilisables, y compris dans un but commercial », à condition de citer l'auteur ([conditions générales de Hub'Eau](https://hubeau.eaufrance.fr/page/conditions-generales)). Les conditions ne précisent pas la version de la Licence Ouverte, et les producteurs restent seuls responsables de leurs données |
| Plan IGN (fond de carte du dashboard) | IGN (Géoplateforme, `data.geopf.fr`) | Licence Ouverte 2.0 ([fiche Plan IGN sur data.gouv.fr](https://www.data.gouv.fr/datasets/plan-ign), vérifié le 2026-10-23). [CGU de cartes.gouv.fr](https://cartes.gouv.fr/cgu) (version du 15 octobre 2024) : les flux WMTS publics ne sont pas soumis à limite d'usage, mais l'IGN peut bloquer l'accès en cas d'usage abusif. La mention « © IGN – Plan IGN » est affichée sur la carte |
| Communes, contour du territoire | geo.api.gouv.fr (DINUM, Etalab) | « Toutes les données utilisées » sont sous licences Open Data ([fiche de l'API sur data.gouv.fr](https://www.data.gouv.fr/dataservices/672cf6946a8456f417812b0f), vérifié le 2026-10-23), sans autre détail. Les contours viennent vraisemblablement d'Admin Express de l'IGN, sous Licence Ouverte 2.0, mais la page de l'API ne le dit pas : à confirmer si le point devient important |
| **Remplissage des retenues d'eau potable** | Département de la Vendée (table ArcGIS publique) | **aucune licence publiée : non couvert par la Licence Ouverte ci-dessus**. Ces relevés sont affichés à titre d'information et restent la propriété de leur producteur. |
