# CLAUDE.md — Observatoire de la sécheresse Vendée

Pour reprendre le projet, lire d'abord `passation.md` (état d'avancement, erreurs corrigées, reste à faire). Lire `docs/SPEC.md` avant toute tâche : c'est la référence pour l'architecture, les sources, le schéma de données et la méthodologie. Les décisions de méthode prises depuis (identifiants D1, D2…) sont dans `docs/methodologie.md` et priment sur la spec en cas d'écart.

## Règles du projet

- **Phases : V0 et V1 terminées, indice validé (octobre 2026).** Ne pas implémenter de fonctionnalités des phases V2 à V4 sans demande explicite. Le schéma et l'arborescence doivent néanmoins rester compatibles avec elles.
- **Les GeoParquet de `data/` sont la source de vérité.** PostGIS est une couche de service, toujours reconstructible avec `make db-rebuild`. Ne jamais écrire de donnée uniquement dans PostGIS.
- **CRS : EPSG:2154** pour le stockage et les calculs. Reprojeter à l'ingestion.
- **Semaine ISO** (`AAAA-Www`) comme unité de temps du suivi.
- **Jamais de valeurs brutes agrégées entre variables** : toujours passer par un indice standardisé (§6 de la spec).
- **Échelle fixe dans le temps (D10)** : la référence reste 1991-2020 (références hors période figées à 2025), jamais glissante ; les valeurs restent bornées. L'indicateur du changement climatique est la part des semaines en classe 1, pas l'intensité des records.
- **Toute modification de la méthode** = une nouvelle décision numérotée dans `docs/methodologie.md` (options chiffrées sur les vraies données, validée par l'utilisateur), `indices.version_methodo` mis à jour dans `config/projet.yaml`, indices recalculés, validation relancée, documents à jour. Décisions actuelles : D1 à D14.
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
make up            # démarre PostGIS et l'API (port 8010)
make referentiels  # communes, mailles SIM, stations -> data/referentiels/
make ingest        # ingestion complète de l'historique
make reference     # calcul des normales
make indices       # indices hebdomadaires de tout l'historique -> data/indices/
make validation    # indices confrontés aux arrêtés sécheresse (VigiEau) -> docs/validation.md
make hebdo         # job hebdomadaire
make qgis          # projet QGIS (QGIS en Docker) -> qgis/ et PostGIS
make site          # dashboard statique -> build/pages (GitHub Pages)
make pages         # make site puis publication sur la branche gh-pages (pousse sur GitHub)
make db-rebuild    # reconstruit PostGIS depuis data/
make test          # sans réseau ni service externe
make test-db       # intégration PostGIS sur une base jetable (Docker)
make lint
```

## Quand un choix n'est pas couvert par la spec

Proposer les options et demander avant d'implémenter, en particulier pour : la pile du front, tout changement de schéma, toute nouvelle source de données, toute modification de la méthodologie des indices.

## Façon de travailler (détail dans `passation.md`, section 2)

- **Git et publication : l'utilisateur committe et pousse lui-même.** Claude prépare, indexe (`git add`) et donne les commandes (blocs `bash` séparés, message en français, ligne `Co-Authored-By`). Jamais de `git commit`, `git push`, `dvc push`, `make hebdo` ni `make pages` lancés par Claude.
- **Décisions** : expliquer simplement les options, les chiffrer sur les vraies données, recommander, puis demander.
- **Vérifier soi-même** avant de livrer : sorties confrontées aux vraies données, idempotence, captures d'écran des rendus (dashboard, schémas, PDF). Tout est généré et testé sur la machine Linux ; le portable ne sert qu'à consulter.
- **Après un changement de `config/`** : `config/` est monté dans le conteneur de l'API et lu au démarrage, donc `docker compose restart api` ; le code et le dashboard sont dans l'image (`make up`).
- **Routine hebdomadaire** (manuelle) : `make up`, `make hebdo`, puis `make pages` pour le site public.
