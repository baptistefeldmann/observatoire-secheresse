# Passation — Observatoire de la sécheresse (Vendée)

État au **2026-10-01**. Ce document permet de reprendre le projet sans l'historique des échanges. À lire avec [`CLAUDE.md`](CLAUDE.md) (règles), [`docs/SPEC.md`](docs/SPEC.md) (référence) et [`docs/methodologie.md`](docs/methodologie.md) (décisions D1 à D8, qui priment sur la spec).

## 1. En bref

- **Objectif** : suivi hebdomadaire de la sécheresse en Vendée, par zone hydrogéologique, à partir des nappes, des débits, des observations ONDE, de la pluie (SIM), du remplissage des retenues, et plus tard de Sentinel-2. Les données servent un dashboard web et QGIS. Le code est générique : un autre département se configure dans `config/`.
- **Avancement** : V0 (spikes) **terminée**. V1 **étapes 1 à 4 terminées** sur 9 (référentiels, ingestion, PostGIS, normales). Prochaine étape : **5, les indices de la semaine**.
- **Dépôts** : code sur GitHub [`baptistefeldmann/observatoire-secheresse`](https://github.com/baptistefeldmann/observatoire-secheresse) (public) ; données sur DagsHub (remote DVC `origin`, `https://dagshub.com/baptistefeldmann/observatoire-secheresse.dvc`).
- **Mode de travail** : Claude prépare et indexe (`git add`) ; **l'utilisateur committe et pousse lui-même** (`git commit`, `git push`, `uv run dvc push`), à partir des commandes que Claude lui donne. Messages de commit en français.

## 2. Environnement

| Élément | Valeur |
|---|---|
| Machine | Linux, `/home/bfeldmann/projects/hydrolyse_dashboard`, 8 cœurs, 31 Go de RAM |
| Python | 3.12 via `uv` (`uv sync`, extra `raster` pour Sentinel-2 : `uv sync --extra raster`) |
| PostGIS | conteneur `secheresse_vendee-postgis-1` (image `postgis/postgis:16-3.4`), port **5433** limité à `127.0.0.1` ; volume Docker persistant ; pas de redémarrage automatique (`make up` après un redémarrage de la machine) |
| Ports déjà pris sur la machine | 5432 (`pg_container`), 8000 (`mlops_meteo_australie-nginx-1`) ; API prévue sur **8010** |
| Secrets | `.env` (non versionné) : mots de passe PostGIS (`POSTGRES_PASSWORD`, `POSTGRES_LECTEUR_PASSWORD`), jeton DagsHub ; `make dvc-auth` les copie dans `.dvc/config.local` |
| Accès QGIS | depuis le portable Windows de l'utilisateur, par tunnel SSH (`ssh -N secheresse-tunnel`), service `secheresse_vendee`, rôle `lecteur` en lecture seule ; **validé** le 2026-09-30. Procédure : [`docs/acces_distant.md`](docs/acces_distant.md) |

## 3. Commandes

```
make config        # valide et affiche la configuration du territoire
make up            # démarre PostGIS
make referentiels  # communes, zones, mailles SIM, stations -> data/referentiels/ (~1 min)
make ingest        # référentiels + historique complet de toutes les sources -> data/raw/ (~10 min)
make reference     # normales + détection des ruptures -> data/normales/ (~20 s)
make db-rebuild    # recharge PostGIS depuis data/ en une transaction (~1 min)
make test          # 70 tests, sans réseau ni service externe
make test-db       # test d'intégration PostGIS sur une base jetable (Docker, port 55433)
make lint          # ruff + mypy strict
```

`make hebdo` n'est pas encore implémenté (étape 6). L'ingestion incrémentale existe déjà : `ingestion.ingerer(config, client, aujourd_hui, depuis=aujourd_hui - 90 jours)`, environ 50 s.

## 4. Ce qui a été fait

### V0 — Spikes (comptes rendus dans `docs/spikes/`)

| Spike | Conclusion |
|---|---|
| n°1 SIM Météo-France | délai d'**un jour** ; aucune source météo complémentaire nécessaire ; grille de 8 km en Lambert II étendu (coordonnées en hectomètres) ; 145 mailles pour la Vendée |
| n°2-3 Hub'Eau | historique long (piézo depuis 1985, débits depuis 1965) ; **aucun piézomètre vendéen en temps réel**, publication par lots (marais breton à jour seulement en mars) ; `profondeur_nappe` est une copie du niveau NGF ; ONDE seulement depuis 2012 |
| n°4 Sentinel-2 | via **Planetary Computer** (choix utilisateur, inspiré du projet `eo_factory`) ; une décade en 3 à 5,5 min ; **offset BOA de −1000 indispensable** (NDVI faussé de 0,13 sinon) ; environ 12 Go de rasters par an |
| n°5 DVC + DagsHub | aller-retour push/pull validé |
| n°6 Retenues | table ArcGIS publique du Département (13 retenues de Vendée Eau, hebdomadaire depuis 2019) ; repli sur la couche nationale de la DREAL Bretagne |

### V1 — Étapes réalisées

1. **Référentiels** (`pipeline/referentiels.py`, `pipeline/sources/`, `pipeline/zonage.py`) : 253 communes, **12 zones**, 145 mailles SIM, 140 stations (56 piézomètres, 41 stations hydrométriques, 30 ONDE, 13 retenues), chacune rattachée à sa zone.
2. **Ingestion** (`pipeline/ingestion.py`, `pipeline/stockage.py`) : un fichier par source et par année dans `data/raw/` ; fusion idempotente (une valeur inchangée garde sa date d'ingestion, une valeur corrigée remplace l'ancienne) ; une station en échec est consignée sans bloquer les autres. Volumes : 429 249 niveaux piézométriques, 396 948 débits, 5 220 observations ONDE, 1,95 million de valeurs météo, 5 239 relevés de retenues. Environ 11 Mo au total.
3. **PostGIS** (`pipeline/db/`) : migration Alembic du schéma `ref` / `obs` / `idx` / `rst` (SPEC §5.3, plus `obs.retenue_semaine`) ; `make db-rebuild` en une transaction (COPY) ; reconstruction à l'identique vérifiée par empreinte (critère n°4 de la V1).
4. **Normales** (`pipeline/reference/`) : SPI 1, 3 et 6 mois par zone (loi gamma, calibration vérifiée), IPS par piézomètre et par mois (37 stations), indice de débit par station et par semaine (29 stations) ; détection des ruptures à chaque calcul.

### Décisions de méthode (détail dans `docs/methodologie.md`)

| Id | Décision |
|---|---|
| D1 | Un piézomètre n'entre au composite de la semaine que si sa dernière mesure a moins de 45 jours |
| D2 | IPS pondéré à 0,15 dans le bocage |
| D3 | ONDE affiché à part, **hors composite** en V1 |
| D4 | Raccordement des stations hydrométriques successives d'un même site (Tiffauges seulement) |
| D5 | Zones = union de masses d'eau souterraine (SANDRE), éventuellement croisée avec les zones d'alerte (SANDRE `ZAS`) ; **12 zones** : Sud-Vendée, marais poitevin, marais breton, Noirmoutier, Yeu, 7 sous-zones du bocage par bassin versant |
| D6 | Retenues d'eau potable : nouvelle source, affichée hors composite |
| D7 | Normales : critère **par période** (mois valide si au moins 10 jours de mesures ; Q7 si au moins 5 jours sur 7, à ±15 jours) ; SPI calculé sur la **pluie moyenne de la zone** |
| D8 | Stations à **rupture de fonctionnement** : détection automatique (test de Pettitt), traitement d'une liste **validée à la main** dans `config/stations.yaml` ; référence limitée au nouveau régime dès 8 ans, avec avertissement |

Pondérations du composite (`config/zones.yaml`) : Sud-Vendée 0,25 / 0,50 / 0,25 ; marais 0,30 / 0,40 / 0,30 ; îles 0,40 / 0,60 / 0 ; bocage 0,40 / 0,15 / 0,45 (SPI 3 mois / IPS / débits).

## 5. Erreurs commises et corrigées

Les leçons à retenir sont en gras.

| Étape | Erreur | Correction |
|---|---|---|
| Squelette | Le healthcheck de PostGIS déclarait la base prête pendant l'initialisation (serveur temporaire sur socket) : `make up` rendait la main trop tôt | `pg_isready -h 127.0.0.1` (TCP) |
| Squelette | Port PostGIS ouvert sur toutes les interfaces | limité à `127.0.0.1`, accès distant par tunnel SSH |
| Accès distant | Un même alias SSH pour Git et pour le tunnel : chaque `git pull` aurait tenté de rouvrir les ports | deux entrées `secheresse` et `secheresse-tunnel` |
| Spike Sentinel-2 | Pixels hors territoire écrits à −32767 au lieu du nodata −32768 (écrêtage appliqué après le remplissage) | écrêter **puis** remplir ; fichiers régénérés |
| Spike Sentinel-2 | Nombre d'observations dupliqué en int16 dans chaque COG | COG de qualité séparé en uint8 (2,7 Mo) |
| Zonage | Fichier VigiEau « en vigueur » utilisé comme référentiel des zones d'alerte : il ne contient que les zones sous arrêté du jour. Un téléchargement de 7,9 Go (30 Go décompressés) a dû être supprimé | référentiel SANDRE `ZAS` (complet, 12 s). **Vérifier la taille d'une ressource avant de la télécharger** |
| Retenues | Numéros « Semaine NN » de la source non ISO (26 % d'écarts) ; table du total depuis 2012 décalée d'une semaine | semaine déduite de la **date** ; table du total non ingérée |
| Retenues | Couche nationale : géométries `MultiPoint` (dont une aberrante) et chaînes vides au lieu de valeurs nulles ; conversion 4,1 × 10⁶ = 4 099 999,999… | lecture de toute géométrie ponctuelle, chaînes vides traitées comme manquantes, arrondi au m³ |
| Ingestion | ONDE : code de campagne entier dans `campagnes`, texte dans `observations` ; la jointure échouait silencieusement | conversion en texte des deux côtés |
| Ingestion | **Défaut grave du stockage** : avec les types nullables de pandas, `<NA> == "x"` vaut `<NA>`, traité comme une égalité ; une valeur manquante complétée à la source n'aurait **jamais** été mise à jour | `fillna(False)` sur la comparaison + test dédié. **Se méfier des comparaisons avec les types nullables** |
| Ingestion | Observations ONDE de stations absentes du référentiel : `db-rebuild` aurait échoué sur la clé étrangère | filtrage sur le référentiel à l'ingestion |
| Vérification | `md5sum -c` affiche « Réussi » et non « OK » en locale française : un contrôle d'idempotence a été mal lu | `LC_ALL=C` |
| Normales | Plantage sans données suffisantes (plage d'années vide) | tables vides au bon schéma |
| Normales | **Non-stationnarité ignorée au départ** : 9 piézomètres sur 38 (Noirmoutier, marais breton) ont changé de régime ; L'Épine aurait été « très haut » en permanence. Repéré par l'utilisateur dans QGIS | D8 : détection + liste validée + référence post-rupture |

Plusieurs défauts n'ont été trouvés qu'en confrontant le code aux **vraies données**, ou par les tests sur réponses enregistrées. Garder cette pratique : contrôler les sorties (effectifs, plages de dates, doublons, idempotence) après chaque étape.

## 6. Ce qu'il reste à faire

### V1 (dans l'ordre)

| # | Étape | Contenu | Points d'attention |
|---|---|---|---|
| **5** | **Indices de la semaine** | Pour une semaine ISO : SPI par zone ($\Phi^{-1}(q_0 + (1-q_0)F_\gamma(x))$) ; IPS par piézomètre (rang non paramétrique dans `valeurs_ref`, règle de fraîcheur D1) ; indice de débit (Q7 du dimanche, rang dans `valeurs_ref`) ; part d'assecs ONDE (affichée) ; indices par zone ; composite avec renormalisation des poids ; classes 1-7 (`config/classes.yaml`) ; écriture de `data/indices/indices_hebdo_<annee>.parquet` et des tables `idx.*` | Semaine 53 → normale de la semaine 52 ; `version_methodo` ; la moyenne d'indices standardisés par zone a une variance inférieure à 1 (à discuter si les classes extrêmes deviennent rares) ; IPS absent pour Noirmoutier (D8) |
| 6 | Job hebdomadaire | `make hebdo` : ingestion incrémentale (90 jours) → indices → `dvc add/push`, commit et tag `data-AAAA-Www` → rechargement de PostGIS → rapport ; cron le lundi | idempotence (critère n°10) ; le job committe lui-même, alors que l'utilisateur committe à la main jusqu'ici : à discuter |
| 7 | Projet QGIS | `qgis/secheresse_vendee.qgz` + styles QML des 7 classes, connexion par service | pas de mot de passe dans le projet |
| 8 | API | FastAPI, endpoints du §8.1 (port 8010) | service des rasters (`/rasters`) en V2 |
| 9 | Dashboard | **React + MapLibre + ECharts** (recommandé ; à inscrire dans la spec §10 après confirmation de l'utilisateur) | carte des zones par semaine, séries avec l'enveloppe de la normale, retenues et ONDE hors composite |

### Points ouverts

- **Pile du front** : React + MapLibre + ECharts proposée, pas formellement confirmée.
- **Ruptures signalées non traitées** : 05342X0073/F (jugée faux positif) et 05863X0203/F (+0,3 m en 2010), à trancher par l'utilisateur.
- **Origine des ruptures** de Noirmoutier et du marais breton : à documenter auprès du BRGM ou des gestionnaires.
- **Raccordements non retenus** : Yon (Nesmy / Chaillé, 5 jours communs ; possible avec un ajustement par surface de bassin), Boulogne.
- **Retenues** : la source ArcGIS du Département est fragile (nom de service changeant, suffixe `_TEST`, pas de licence) ; l'utilisateur ne souhaite pas contacter Vendée Eau pour l'instant.
- **`restart: unless-stopped`** pour PostGIS : proposé, non appliqué.
- **CI GitHub Actions** (lint + tests) : proposée, non faite.
- **Dépôt GitHub public** et indexé par les moteurs de recherche : à passer en privé si besoin.

### Après la V1

- **Valider l'indice sur les sécheresses passées** (2011, 2017, 2019, 2022) contre les arrêtés et le bulletin de situation hydrologique : indispensable avant toute présentation à des acteurs (DDTM 85, Vendée Eau, syndicats de bassin).
- **V2** : composites Sentinel-2 (NDVI/NDMI par décade), carte d'occupation du sol interne, anomalies par classe ; seuil minimal d'observations valides ; écriture par blocs (RAM) ; prévoir 12 Go par an dans `rasters/`.
- **V3** : axe pression (population touristique, prélèvements, réserves de substitution du Marais poitevin) ; la place naturelle des retenues est l'axe « tension ».
- **V4** : prévision.

## 7. Contexte utile

- **Existant** : Info-Sécheresse (imaGeau) couvre déjà nappes, débits et pluie classés sur 7 niveaux, chaque jour ; la DDTM 85 produit un bulletin hebdomadaire en période de tension. La valeur ajoutée du projet tient à la **lecture par les 12 zones vendéennes**, à l'**indice composite à méthode publiée**, au **satellite par type d'occupation du sol (V2)** et à la **réplicabilité**.
- **94 % de l'eau potable vendéenne vient des retenues** : l'indicateur le plus suivi localement.
- **Stockage** : `data/` pèse 15 Mo (versionné sur DagsHub) ; le dossier du projet 1,3 Go, surtout `.venv` (892 Mo) et les rasters du spike (313 Mo, dans `rasters/spike_v0/`, conservés à la demande de l'utilisateur).
