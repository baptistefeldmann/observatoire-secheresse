# CLAUDE.md — Observatoire de la sécheresse Vendée

Pour reprendre le projet, lire d'abord `passation.md` (état d'avancement, erreurs corrigées, reste à faire). Lire `docs/SPEC.md` avant toute tâche : c'est la référence pour l'architecture, les sources, le schéma de données et la méthodologie. Les décisions de méthode prises depuis (identifiants D1, D2…) sont dans `docs/methodologie.md` et priment sur la spec en cas d'écart.

## Règles du projet

- **Phase en cours : V0 puis V1.** Ne pas implémenter de fonctionnalités des phases V2 à V4 sans demande explicite. Le schéma et l'arborescence doivent néanmoins rester compatibles avec elles.
- **Les GeoParquet de `data/` sont la source de vérité.** PostGIS est une couche de service, toujours reconstructible avec `make db-rebuild`. Ne jamais écrire de donnée uniquement dans PostGIS.
- **CRS : EPSG:2154** pour le stockage et les calculs. Reprojeter à l'ingestion.
- **Semaine ISO** (`AAAA-Www`) comme unité de temps du suivi.
- **Jamais de valeurs brutes agrégées entre variables** : toujours passer par un indice standardisé (§6 de la spec).
- `rasters/` n'est ni versionné par Git ni par DVC.
- Les secrets (Météo-France, Copernicus, DagsHub) sont lus depuis `.env`. Ne jamais les écrire dans le code, la configuration versionnée ou les projets QGIS. Maintenir `.env.example` à jour.
- Toute étape du pipeline est idempotente.
- **Généricité territoriale** : aucune référence à la Vendée dans le code (code département, noms de zones, emprise, noms de fichiers). Tout ce qui est propre au territoire vit dans `config/projet.yaml` (bloc `territoire`), `config/zones.yaml` et `config/stations.yaml` (facultatif) ; les noms de fichiers utilisent `territoire.slug`.

## Conventions de code

- Python 3.12, `uv`, `ruff`, `mypy`.
- Un module par source dans `pipeline/sources/`, exposant une fonction d'ingestion qui renvoie un GeoDataFrame normalisé.
- Paramètres dans `config/*.yaml`, pas de constante métier en dur (code département, seuils, pondérations).
- Tests avec `pytest` et des réponses API enregistrées dans `tests/fixtures/` : aucun test ne doit dépendre du réseau.
- Noms de tables, colonnes et variables métier en français, cohérents avec la spec.

## Commandes (Makefile)

```
make config        # valide et affiche la configuration du territoire
make up            # démarre PostGIS
make referentiels  # communes, mailles SIM, stations -> data/referentiels/
make ingest        # ingestion complète de l'historique
make reference     # calcul des normales
make indices       # indices hebdomadaires de tout l'historique -> data/indices/
make hebdo         # job hebdomadaire
make db-rebuild    # reconstruit PostGIS depuis data/
make test          # sans réseau ni service externe
make test-db       # intégration PostGIS sur une base jetable (Docker)
make lint
```

## Quand un choix n'est pas couvert par la spec

Proposer les options et demander avant d'implémenter, en particulier pour : la pile du front, tout changement de schéma, toute nouvelle source de données, toute modification de la méthodologie des indices.
