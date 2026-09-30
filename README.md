# Observatoire de la sécheresse

Suivi hebdomadaire de la sécheresse à l'échelle d'un département : nappes, débits, écoulement (ONDE), météo (SIM), puis télédétection Sentinel-2 et occupation du sol. Instance de référence : **Vendée (85)**.

La spécification complète est dans [`docs/SPEC.md`](docs/SPEC.md).

## Démarrage

Prérequis : [uv](https://docs.astral.sh/uv/), Docker, make.

```bash
cp .env.example .env      # renseigner POSTGRES_PASSWORD et POSTGRES_LECTEUR_PASSWORD
make install
make dvc-auth             # identifiants DagsHub (DAGSHUB_USER, DAGSHUB_TOKEN dans .env)
dvc pull                  # récupère data/ depuis DagsHub
make config               # vérifie la configuration du territoire
make up                   # démarre PostGIS
make test
```

`make help` liste toutes les commandes.

Pour utiliser QGIS depuis un autre poste (Windows) via SSH : [`docs/acces_distant.md`](docs/acces_distant.md).

## Adapter à un autre département

Le code ne contient aucune référence au territoire : tout passe par `config/`.

1. Copier le dépôt (sans `data/`, qui est propre au territoire).
2. Dans `config/projet.yaml`, bloc `territoire` : `code_departement`, `nom`, `slug`.
   En outre-mer, remplacer aussi `crs` par la projection officielle locale.
3. Réécrire `config/zones.yaml` : zones de lecture du territoire et pondérations de l'indice composite.
   Vider ou adapter `config/stations.yaml` (raccordements de stations hydrométriques).
4. Dans `.env` : `COMPOSE_PROJECT_NAME`, `POSTGRES_DB` et, si plusieurs instances tournent sur la même machine, `POSTGRES_PORT`.
5. Créer un dépôt DagsHub pour le territoire et remplacer l'URL du remote : `dvc remote modify origin url https://dagshub.com/<compte>/<depot>.dvc`, puis `make dvc-auth`.
6. `make config` pour valider, puis `make ingest` et `make reference`.

`classes.yaml` (échelle à 7 classes) et `sources.yaml` (points d'accès des API) sont communs à tous les départements.

## Arborescence

```
config/      paramètres (territoire, zones, classes, sources)
pipeline/    ingestion, indices, normales, chargement PostGIS
api/         FastAPI (à venir)
dashboard/   front web (pile à arrêter)
qgis/        projet et styles QGIS
data/        GeoParquet, source de vérité (DVC)
rasters/     COG Sentinel-2, locaux et non versionnés
docs/        spécification, méthodologie, comptes rendus de spikes
```
