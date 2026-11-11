# Licence des données

Le **code** de l'observatoire est sous licence MIT (fichier [`LICENSE`](LICENSE)). Les **données** relèvent de deux régimes : celles que l'observatoire produit, sous Licence Ouverte, et celles des fournisseurs, qui gardent leurs propres conditions.

## Données produites par l'observatoire

Sous [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/) (Etalab) : réutilisation libre, y compris commerciale, à condition de citer la source et la date de mise à jour.

| Données | Emplacement |
|---|---|
| Indices hebdomadaires (stations, zones, composite) | `data/indices/`, tables `idx.*`, API, site public |
| Normales de référence, enveloppes, ruptures détectées | `data/normales/` |
| Découpage en zones et rattachement des stations | `data/referentiels/zones.parquet`, `stations.parquet` |
| *V2, à venir* : surface de crue des marais (hectares par mois), anomalies de NDVI et de NDMI par zone et par classe | `idx.satellite_mois`, API, site public. **La surface de crue par régime (marais mouillé, intermédiaire, desséché) dépend de la couche de l'EPMP : voir ci-dessous** |

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

## Sources de la V2 (satellite), en préparation

Rien de la V2 n'est encore publié : cette section fixe les conditions des sources avant l'implémentation. Mention à prévoir sur le site : « Contains modified Copernicus Sentinel data » (année), plus les crédits ci-dessous.

| Source | Producteur | Conditions |
|---|---|---|
| Sentinel-2 L2A (NDVI, NDMI) | ESA / Copernicus, via Microsoft Planetary Computer | Conditions des données Sentinel de Copernicus (libre et ouvert, mention « Contains modified Copernicus Sentinel data »). La collection STAC indique « Copernicus Sentinel data terms » (vérifié le 2026-11-11) |
| Sentinel-1 RTC (crue) | ESA / Copernicus ; produit RTC de Catalyst et Microsoft, via Planetary Computer | **CC BY 4.0** (collection STAC `sentinel-1-rtc`, vérifié le 2026-11-11) : citer Catalyst et Microsoft, et la mention Copernicus ci-dessus |
| BD Forêt V2 (classes de forêt) | IGN, Inventaire forestier national | Licence Ouverte 2.0 d'après la spécification du projet, **à reconfirmer** sur la fiche de l'IGN |
| RPG (classes de culture, prairies) | IGN / Agence de services et de paiement | Licence Ouverte attendue, **à confirmer** |
| BD TOPO (réseau maritime, eau permanente, estran) | IGN (Géoplateforme) | Licence Ouverte 2.0 attendue, **à confirmer** |
| CORINE Land Cover 2018 (marais salants, plages et dunes) | Union européenne, Copernicus Land Monitoring Service, via Géoplateforme | libre d'accès, mention « © European Union, Copernicus Land Monitoring Service 2018, European Environment Agency (EEA) » : **à confirmer** |
| Hauteurs de marée (contrôle de marée) | SHOM, REFMAR | Licence Ouverte Etalab 2.0 d'après le site de REFMAR (relevé en V2.0) ; l'API JSON publique utilisée n'est pas documentée |
| Carte d'arbres récente (mise à jour des classes de forêt) | Impact Observatory, Microsoft et Esri : « 10m Annual Land Use Land Cover (9-class) », 2017-2023 | **CC BY 4.0** (vérifié le 2026-11-11 sur la collection STAC, le registre AWS et la page d'Impact Observatory). Citation proposée par le registre AWS : « 10m Annual Land Use Land Cover (9-class) was accessed on DATE from https://registry.opendata.aws/io-lulc » ; citer aussi Impact Observatory, Microsoft et Esri. Usage en masque seulement ; l'usage pour entraîner un modèle commercial n'est pas tranché juridiquement (non prévu) |
| ESA WorldCover 2021 (à défaut de la carte ci-dessus) | ESA | CC BY 4.0 (collection STAC) |
| **Grandes entités du Marais poitevin (marais mouillé, intermédiaire, desséché ; cordons dunaires)** | Établissement public du Marais poitevin (EPMP), portail SIG | **aucune licence indiquée par l'EPMP.** Décision de l'utilisateur du 2026-11-11 : **considérée comme utilisable pour le prototype, à confirmer auprès de l'EPMP** (question Q17, voir `passation.md`). Les fichiers de l'EPMP ne sont pas versionnés (`docs/*.gpkg` est ignoré) ; seule la surface de crue par régime en dérive. À régler avant toute communication externe |

Le Marais breton est traité en un seul bloc (aucune couche de régimes n'existe pour lui : décision Q15).
