# Observatoire de la sécheresse — Vendée (85)

Spécification de référence du projet. Ce document décrit le contexte, l'architecture, les sources de données, le modèle de données et le découpage en phases. Il sert de point de départ pour le développement assisté par Claude Code.

Version : 0.1 — septembre 2026

---

## 1. Contexte et objectifs

L'objectif est de construire un outil de suivi hebdomadaire de la sécheresse sur le département de la Vendée, combinant données hydrologiques, météorologiques et satellitaires, et de l'étendre progressivement vers une estimation de la tension sur la ressource en eau et sa prévision à court terme.

Les outils officiels existants (VigiEau pour les restrictions, Bulletin de situation hydrologique mensuel) donnent une vue administrative ou mensuelle. La valeur ajoutée de ce projet repose sur trois points : une fréquence hebdomadaire, une lecture par zone hydrogéologique à l'intérieur du département, et l'intégration de la télédétection (Sentinel-2) et d'une carte d'occupation du sol produite par un modèle interne.

Deux clients consomment les mêmes données : un dashboard web et QGIS.

### Principes directeurs

1. **Indices standardisés, jamais de valeurs brutes mélangées.** Chaque variable est comparée à sa propre normale (même station ou même pixel, même période de l'année) avant toute agrégation.
2. **Lecture par zone hydrogéologique.** La Vendée n'est pas homogène : Sud-Vendée sédimentaire (nappes du Lias-Dogger), marais (breton et poitevin), bocage sur socle armoricain (nappes peu profondes et réactives). Les pondérations de l'indice composite diffèrent par zone.
3. **Deux axes distincts** (à partir de la V3) : l'état de la ressource (sécheresse physique) et la pression de la demande. Leur croisement donne la tension. La population et les prélèvements ne sont jamais injectés dans l'indice physique.
4. **Reproductibilité.** Les données tabulaires sont versionnées (DVC) ; les rasters Sentinel-2 ne le sont pas, car ils sont régénérables à partir de l'archive Copernicus et du code versionné.
5. **Généricité territoriale.** La Vendée est l'instance de référence, mais le code ne contient aucune référence au territoire. Le département, son `slug` (utilisé dans les noms de fichiers) et les zones sont définis dans `config/projet.yaml` et `config/zones.yaml` ; adapter l'outil à un autre département ne demande que ces deux fichiers, un `.env` et un remote DVC propres.

---

## 2. Périmètre par phase

| Phase | Contenu | Statut |
|---|---|---|
| **V0** | Spikes de validation technique (voir §9) | À faire en premier |
| **V1** | Suivi de la ressource : météo, nappes, débits, ONDE ; indices standardisés ; agrégation par zone ; dashboard minimal ; projet QGIS | Cible principale |
| **V2** | Sentinel-2 : NDVI, NDMI, anomalies, composites 10 jours ; intégration de la carte d'occupation du sol interne ; anomalies par classe | Architecture à anticiper |
| **V3** | Axe pression : population présente estimée par commune et par mois, prélèvements BNPE, surfaces irriguées ; carte de tension | Architecture à anticiper |
| **V4** | Prévision : nappes à 1–2 mois, scénarios par années analogues, demande saisonnière | Architecture à anticiper |

La V1 doit être complète et fonctionnelle avant d'attaquer la V2. Les phases suivantes ne sont pas à implémenter maintenant, mais le schéma de données et l'arborescence doivent pouvoir les accueillir sans refonte.

---

## 3. Architecture

```
                    SOURCES (APIs ouvertes)
 ┌──────────────┬──────────────┬──────────────┬─────────────────────┐
 │ Météo-France │ Hub'Eau      │ Hub'Eau      │ Sentinel-2 L2A      │
 │ SIM (SAFRAN) │ Piézométrie  │ Hydrométrie  │ (STAC, COG)   [V2]  │
 │              │              │ + Écoulement │                     │
 └──────┬───────┴──────┬───────┴──────┬───────┴──────────┬──────────┘
        └──────────────┴──────┬───────┘                  │
                              ▼                          ▼
              ┌───────────────────────────────────────────────────┐
              │  PIPELINE PYTHON (job hebdomadaire, lundi matin)  │
              │  ingestion → GeoParquet (DVC) → indices → PostGIS │
              └───────────┬──────────────────────────┬────────────┘
                          ▼                          ▼
   ┌───────────────────────────────┐    ┌─────────────────────────────┐
   │ GeoParquet versionnés (DVC)   │    │ COG locaux (non versionnés) │
   │ = SOURCE DE VÉRITÉ            │    │ NDVI, NDMI, anomalies [V2]  │
   │ remote : DagsHub              │    └──────┬──────────────┬───────┘
   └───────────────┬───────────────┘           │              │
                   ▼ (rechargement)            │              │
   ┌───────────────────────────────┐           │              │
   │ PostGIS (Docker, local)       │           │              │
   │ = COUCHE DE SERVICE           │           │              │
   └──────┬──────────────┬─────────┘           │              │
          │              ▼                     ▼              │
          │     ┌───────────────────────────────────┐         │
          │     │ API : FastAPI + TiTiler           │         │
          │     └────────────────┬──────────────────┘         │
          ▼                      ▼                            ▼
   ┌─────────────┐     ┌──────────────────────────────────────────┐
   │ QGIS        │     │ Dashboard web (MapLibre + graphiques)    │
   │ PostGIS+COG │     └──────────────────────────────────────────┘
   └─────────────┘
```

### Stockage et versionnage

| Donnée | Emplacement | Versionnage |
|---|---|---|
| Code, configuration, schéma SQL | Git (GitHub, relié à DagsHub) | Git |
| Données brutes API (GeoParquet) | `data/raw/` | DVC → remote DagsHub |
| Indices calculés (GeoParquet) | `data/indices/` | DVC → remote DagsHub |
| Référentiels (stations, zones) | `data/referentiels/` | DVC → remote DagsHub |
| Carte d'occupation du sol (un fichier par millésime) | `data/occupation_sol/` | DVC → remote DagsHub |
| Rasters Sentinel-2 (COG) | `rasters/` (local) | Non versionné, dans `.gitignore` et `.dvcignore` |
| Base PostGIS | Conteneur Docker, volume local | Non versionnée : reconstruite depuis les Parquet |

**Règle clé : PostGIS n'est jamais la source de vérité.** Un `dvc pull` suivi de `make db-rebuild` doit reconstruire intégralement la base.

Le code est hébergé sur GitHub (intégration continue possible avec GitHub Actions) ; le dépôt DagsHub y est relié et fournit le remote DVC. Le remote DVC DagsHub est distinct du bucket S3 DagsHub : on utilise uniquement le **remote DVC** (`https://dagshub.com/<compte>/<depot>.dvc`, authentification par jeton, copiée de `.env` vers `.dvc/config.local` par `make dvc-auth`). Quota gratuit : 10 Go par dépôt, largement suffisant pour les données tabulaires si on respecte le découpage par année (§5.2). Validé par le [spike n°5](spikes/05_dvc_dagshub.md).

---

## 4. Sources de données

Toutes les sources sont ouvertes et gratuites. Les identifiants (Météo-France, Copernicus, DagsHub) sont lus depuis un fichier `.env` jamais commité.

### 4.1 Hub'Eau — Piézométrie (V1)

- Base : `https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/`
- Endpoints : `stations`, `chroniques` (historique journalier validé), `chroniques_tr` (temps réel horaire, ~1700 piézomètres en France)
- Filtre : `code_departement=85`
- Formats : JSON, GeoJSON, CSV. Pas de clé.
- État constaté (sept. 2026) : 56 stations en Vendée, dont 41 avec des mesures en 2026, concentrées sur le Sud-Vendée (Lias-Dogger) et le marais breton ; le socle en compte 9, dont 5 avec au moins 15 ans de référence. Aucune station en temps réel, publication par lots : voir le [spike n°2](spikes/02-03_hubeau_historique.md).
- Seul `niveau_nappe_eau` (cote NGF) est exploitable : `profondeur_nappe` en est une copie ([méthodologie](methodologie.md)).
- Identifiant stable : `code_bss` (et `bss_id` depuis v1.4.3).

### 4.2 Hub'Eau — Hydrométrie (V1)

- Base : `https://hubeau.eaufrance.fr/api/v2/hydrometrie/`
- Endpoints : `referentiel/stations`, `obs_elab` (débits moyens journaliers `QmnJ`, mensuels `QmM`, historique depuis 1900 pour certaines stations), `observations_tr` (hauteur et débit temps réel, profondeur d'historique 1 mois seulement)
- Unités : hauteurs en mm, débits en l/s.
- État constaté : 41 stations en Vendée, 30 en service (`en_service = true`).
- Pour le suivi hebdomadaire, utiliser `obs_elab` / `QmnJ`. `observations_tr` n'est utile que pour l'affichage « dernière valeur ».

### 4.3 Hub'Eau — Écoulement des cours d'eau / ONDE (V1)

- Base : `https://hubeau.eaufrance.fr/api/v1/ecoulement/`
- Endpoints : `stations`, `campagnes`, `observations`
- Observations visuelles de l'OFB (écoulement visible / non visible / assec), campagnes d'avril à novembre en Vendée (usuelles mensuelles, complémentaires en période de sécheresse), pas de mesure continue. Historique depuis 2012.
- État constaté : 30 stations actives en Vendée.
- Traitement : proportion de stations en assec ou en rupture d'écoulement par zone et par campagne. **Couche affichée à part, hors indice composite en V1** (méthodologie, D3). Hors saison, la couche est affichée comme « hors période de suivi », jamais comme zéro.

### 4.4 Météo-France — SIM / SAFRAN (V1)

- Données quotidiennes de la chaîne Safran-Isba-Modcou, sur une grille d'environ 8 km, publiées sur data.gouv.fr (jeu « Données changement climatique - SIM quotidienne »).
- Variables utiles : précipitations (liquides + solides), ETP, humidité des sols (SWI).
- **Validé en V0** ([spike n°1](spikes/01_sim_meteo.md)) : délai d'un jour (fichier `QUOT_SIM2_latest`, 60 jours glissants), un fichier CSV par année depuis 1958, grille de 8 km en Lambert II étendu (coordonnées en hectomètres), 145 mailles pour la Vendée avec un tampon de 1 km, identifiées par `num_maille`.
- L'API Données Publiques Climatologie de `portail-api.meteofrance.fr` (données station, compte gratuit) n'est pas nécessaire en V1.

### 4.5 Référentiels (V1)

- Communes et contour départemental : `https://geo.api.gouv.fr/departements/85/communes?format=geojson&geometry=contour` (contour obtenu par fusion).
- Masses d'eau souterraine : WFS SANDRE (`PolygMasseDEauSouterraine_VEDL2019_FXX`, horizon 1, codes identiques aux champs `codes_masse_eau_edl` des stations piézométriques).
- Zones d'alerte sécheresse : WFS SANDRE (`ZAS_FXX`, statut « Validé », code `CdZAS`) ; l'API VigiEau donne les mêmes zones sans géométrie.
- Découpage en zones : union de masses d'eau, éventuellement croisée avec des zones d'alerte ([méthodologie, D5](methodologie.md)) ; `data/referentiels/zones.parquet`.

### 4.5 bis Retenues d'eau potable (V1, ajout du 2026-09-30)

- Remplissage hebdomadaire des retenues (volume, capacité) : table ArcGIS publique propre au territoire (`config/stations.yaml`, bloc `retenues` ; Vendée : données Vendée Eau publiées par le Département, 13 retenues depuis 2019), et repli sur la couche nationale de la DREAL Bretagne (`dreal_b:qry_remplissage_retenues`, dernière semaine seulement).
- Affiché hors indice composite ([méthodologie, D6](methodologie.md), [spike n°6](spikes/06_retenues.md)).

### 4.6 Sentinel-2 L2A (V2)

- Catalogue retenu : **Microsoft Planetary Computer** (API STAC, collection `sentinel-2-l2a`, COG sur Azure). Les URL des assets sont signées par `planetary_computer.sign` (jeton SAS d'environ 1 h, appliqué par odc-stac à la construction du graphe Dask : un calcul de plus de 45 minutes doit re-signer). Accès anonyme ; clé facultative `PC_SDK_SUBSCRIPTION_KEY` pour un quota élargi. Même approche que le projet interne `eo_factory`.
- La collection **n'est pas harmonisée** : appliquer l'offset BOA de −1000 aux scènes de baseline ≥ 04.00 (propriété `s2:processing_baseline`, toutes les scènes depuis janvier 2022), sinon les séries seront discontinues et les indices faussés. Paramètres dans `config/sources.yaml` (`sentinel2`).
- Alternatives non retenues : Earth Search (`sentinel-2-c1-l2a`, harmonisée), Copernicus Data Space Ecosystem.
- Bandes : B03, B04, B08, B11, SCL.
- Visualisation rapide dans QGIS : WMS Copernicus Data Space (configuration à créer dans le compte) et mosaïque annuelle EOX `s2cloudless` en fond.

### 4.7 Occupation du sol (V2)

- Carte produite par un **modèle interne** (hors périmètre de ce dépôt dans un premier temps).
- Contrat d'interface à respecter : GeoTIFF/COG, EPSG:2154, résolution 10 m, entier 8 bits, nomenclature documentée dans `config/nomenclature_ocs.yaml`, un fichier par millésime (`ocs_<annee>_<slug>.tif`).
- Classes minimales attendues pour les usages du projet : eau, urbain, forêt, prairie, grandes cultures, cultures irriguées (si possible), marais / zones humides.
- Complément possible : RPG (Registre parcellaire graphique) pour le type de culture à la parcelle.

### 4.8 Sources de la V3 (pour mémoire)

- Hub'Eau Prélèvements en eau (`https://hubeau.eaufrance.fr/api/v1/prelevements/`) : volumes annuels par ouvrage et par usage, diffusés en N+2, uniquement les prélèvements soumis à redevance.
- INSEE : populations légales par commune (annuelles, décalage d'environ 3 ans), résidences secondaires par commune, capacité d'hébergement touristique par commune, fréquentation touristique mensuelle à l'échelle départementale.

---

## 5. Modèle de données

### 5.1 Conventions générales

- CRS de stockage et de calcul : **EPSG:2154** (Lambert 93). Les API renvoient du WGS84 : reprojeter à l'ingestion.
- Semaine de référence : **semaine ISO** (lundi → dimanche), identifiant `AAAA-Www` (ex. `2026-W40`).
- Dates en UTC, sans heure pour les données journalières.
- Chaque table d'observation conserve la date d'ingestion (`ingere_le`) et un indicateur de qualification lorsque la source le fournit (donnée brute / validée), car les données Hub'Eau sont corrigées a posteriori.

### 5.2 Fichiers GeoParquet (source de vérité)

```
data/
├── raw/
│   ├── piezo/chroniques_<annee>.parquet
│   ├── hydro/qmj_<annee>.parquet
│   ├── onde/observations_<annee>.parquet
│   ├── meteo/sim_<annee>.parquet
│   └── retenues/retenues_<annee>.parquet
├── normales/                 # make reference (méthodologie D7)
│   ├── spi_zone.parquet
│   ├── ips_station.parquet
│   └── debit_station.parquet
├── indices/                 # make indices (méthodologie D9), un fichier par table et par année ISO
│   ├── indice_station_<annee>.parquet
│   ├── indice_zone_<annee>.parquet
│   └── composite_zone_<annee>.parquet
├── referentiels/
│   ├── stations.parquet
│   ├── zones.parquet
│   ├── mailles_safran.parquet
│   └── communes.parquet
└── occupation_sol/
    └── ocs_<annee>_<slug>.tif
```

Un fichier par source et par année : chaque semaine, seul le fichier de l'année en cours change, ce qui limite le volume stocké par DVC (qui conserve chaque version entière).

### 5.3 Schéma PostGIS

Quatre schémas de tables : `ref` (référentiels), `obs` (observations), `idx` (indices), `rst` (catalogue raster) ; un schéma de vues de restitution, `carto` (migration 0003).

```sql
-- Référentiels
ref.zone (
  zone_id        text primary key,     -- ex. 'SUD_VENDEE', 'MARAIS_BRETON', 'BOCAGE'
  libelle        text,
  type_zone      text,                 -- 'hydrogeol' | 'alerte'
  ponderations   jsonb,                -- poids de chaque indice dans le composite
  geom           geometry(MultiPolygon, 2154)
)

ref.station (
  station_id     text primary key,     -- '<source>:<code>' ex. 'piezo:05912X0012/F'
  source         text,                 -- 'piezo' | 'hydro' | 'onde' | 'retenue'
  code           text,
  libelle        text,
  en_service     boolean,
  masse_eau      text,
  zone_id        text references ref.zone,
  metadonnees    jsonb,
  geom           geometry(Point, 2154)
)

ref.maille_safran (maille_id int primary key, geom geometry(Polygon, 2154))
ref.commune (code_insee text primary key, nom text, geom geometry(MultiPolygon, 2154))

-- Observations
obs.piezo_jour  (station_id, date, niveau_ngf, profondeur, qualification, ingere_le)
obs.debit_jour  (station_id, date, qmj_ls, qualification, ingere_le)
obs.onde        (station_id, date_campagne, modalite, type_campagne, ingere_le)
obs.meteo_jour  (maille_id, date, precip_mm, etp_mm, swi, ingere_le)
obs.retenue_semaine (station_id, date, volume_m3, capacite_m3, source_donnee, ingere_le)  -- D6

-- Indices hebdomadaires
idx.indice_station (station_id, semaine, indice, valeur, classe, periode_ref, hors_reference,
                    date_mesure, dans_composite, version_methodo)          -- colonnes D1, D9
idx.indice_zone    (zone_id,    semaine, indice, valeur, classe, n_stations, detail jsonb,
                    version_methodo)                                       -- ONDE : D3, D9
idx.composite_zone (zone_id,    semaine, valeur, classe, detail jsonb, version_methodo)

-- Vues de restitution (migration 0003) : indices joints à leur géométrie, pour QGIS et l'API.
-- Colonnes communes : cle (identifiant unique), semaine, debut (lundi), fin (dimanche),
-- derniere (semaine la plus récente ; dernière campagne ONDE ; dernier relevé de retenue).
carto.v_composite_zone, carto.v_indice_zone, carto.v_onde_zone      -- géométrie de la zone
carto.v_indice_station, carto.v_retenue                             -- géométrie de la station

-- Catalogue raster [V2]
rst.produit (
  produit_id     serial primary key,
  indice         text,                 -- 'ndvi' | 'ndmi' | 'ndvi_anomalie' ...
  date_debut     date, date_fin date,
  resolution_m   int,
  chemin         text,                 -- chemin local du COG
  pct_pixels_valides real,
  emprise        geometry(Polygon, 2154)
)
```

Clés primaires composites sur les tables d'observation et d'indices (identifiant + date/semaine + indice). Index spatiaux GIST sur toutes les géométries.

Le champ `version_methodo` permet de faire coexister plusieurs versions de la méthode de calcul. Il vaut l'identifiant de la dernière décision de [méthodologie](methodologie.md) en vigueur (`indices.version_methodo` dans `config/projet.yaml`, D9) ; le lien avec le commit de code passe par le tag `data-AAAA-Www` du job hebdomadaire (§7.1).

---

## 6. Méthodologie des indices

### 6.1 Période de référence

- Données hydrologiques et météo : 1991–2020 lorsque l'historique le permet ; à défaut, toute la période disponible avec au minimum 15 ans, et un avertissement stocké avec l'indice.
- Sentinel-2 : 2018–2025 (L2A disponible de façon homogène à partir de 2018).
- Le calcul des références est un **script séparé** (`pipeline/reference/`), lancé ponctuellement, qui produit des fichiers de normales versionnés. Le job hebdomadaire ne fait que les lire.
- Les stations au fonctionnement modifié (ruptures) sont détectées à chaque calcul et traitées explicitement, avec une référence limitée au nouveau régime ([méthodologie, D8](methodologie.md)).

### 6.2 Indices par variable

| Variable | Indice | Principe |
|---|---|---|
| Précipitations | SPI 1, 3 et 6 mois | Ajustement d'une loi gamma sur les cumuls glissants de la période de référence, transformation en variable normale centrée réduite |
| Nappes | IPS (indicateur piézométrique standardisé) | Niveau moyen mensuel standardisé par rapport à l'historique de la station pour le même mois, classé en 7 niveaux (très bas → très haut), méthode BRGM. Station exclue du composite si sa dernière mesure est trop ancienne (méthodologie, D1) |
| Débits | Indice de débit standardisé | Percentile du débit moyen sur 7 jours par rapport aux débits de la même période sur la référence |
| Écoulement (ONDE) | Part de stations en assec ou rupture | Par zone et par campagne, uniquement en saison. Non standardisé : hors composite en V1 (méthodologie, D3) |
| Végétation [V2] | Anomalie NDVI et NDMI | Écart standardisé par pixel au composite de même période de la référence, puis agrégé **par classe d'occupation du sol** et par zone |

Note sur les indices spectraux : pour le stress hydrique de la végétation, utiliser le **NDMI** (aussi appelé NDWI de Gao) = (B08 − B11) / (B08 + B11). Le NDWI de McFeeters = (B03 − B08) / (B03 + B08) sert à détecter l'eau libre : il est utile pour suivre la surface des barrages-réservoirs, pas pour le stress de la végétation.

### 6.3 Classes communes

Tous les indices sont ramenés sur une échelle commune de 7 classes, alignée sur celle du BSH, pour permettre la comparaison et la symbologie homogène :

| Classe | Libellé | SPI / valeur standardisée |
|---|---|---|
| 1 | Très bas / extrêmement sec | ≤ −1,28 |
| 2 | Bas / modérément sec | −1,28 à −0,84 |
| 3 | Modérément bas | −0,84 à −0,25 |
| 4 | Normal | −0,25 à 0,25 |
| 5 | Modérément haut | 0,25 à 0,84 |
| 6 | Haut | 0,84 à 1,28 |
| 7 | Très haut / extrêmement humide | > 1,28 |

Les seuils sont paramétrables dans `config/classes.yaml`.

### 6.4 Indice composite par zone

Moyenne pondérée des indices standardisés disponibles pour la zone, avec les poids définis dans `ref.zone.ponderations` (alimentés par `config/zones.yaml`). Pondérations V1, après les décisions D2 et D3 de la [méthodologie](methodologie.md) :

| Zone | SPI 3 mois | IPS nappes | Débits | NDVI/NDMI [V2] |
|---|---|---|---|---|
| Sud-Vendée sédimentaire | 0,25 | 0,50 | 0,25 | — |
| Marais (breton, poitevin) | 0,30 | 0,40 | 0,30 | — |
| Îles (Noirmoutier, Yeu) | 0,40 | 0,60 | 0 | — |
| Bocage (socle), 7 sous-zones par bassin versant | 0,40 | 0,15 | 0,45 | — |

Le découpage en 12 zones est décrit en D5 de la méthodologie.

Quand un indice est absent (station en panne, donnée piézométrique trop ancienne), les poids restants sont renormalisés et l'indice composite porte l'information du nombre de composantes utilisées. Le détail des composantes est stocké dans `idx.composite_zone.detail`.

---

## 7. Pipeline

### 7.1 Job hebdomadaire (lundi matin)

1. Ingestion incrémentale de chaque source (re-téléchargement des 90 derniers jours pour capter les corrections a posteriori ; un piézomètre publié par lots est relu depuis sa dernière mesure en stock, pour qu'un lot de plusieurs mois soit récupéré en entier).
2. Écriture des GeoParquet de l'année en cours.
3. Calcul des indices de la semaine écoulée. En pratique, tout l'historique est recalculé (environ 25 s) : chaque correction ou lot reçu se répercute sur les semaines concernées, et un calcul inchangé réécrit des fichiers identiques.
4. `dvc add` + `dvc push`, commit Git des seuls fichiers `data/*.dvc`, tag `data-AAAA-Www`, envoi sur le remote Git. Pas de commit si les données n'ont pas changé, ni hors de la branche `hebdo.branche` ; une semaine recalculée après correction déplace son tag.
5. Rechargement de PostGIS (reconstruction complète, environ 1 min).
6. [V2] Production des composites Sentinel-2 si la fenêtre de 10 jours est complète.
7. Rapport d'exécution dans `logs/hebdo/AAAA-Www.md`, non versionné (stations en échec, couverture de la semaine, anomalies de valeur, composite par zone, publication).

Code : `pipeline/run_hebdo.py` et `pipeline/publication.py`, lancés par `make hebdo` (`--sans-publication` pour ne rien versionner). Orchestration : cron pour la V1, après la publication du SIM de la veille (vers 10 h, heure de Paris) ; Prefect envisageable si le nombre de tâches augmente.

### 7.2 Robustesse

- Requêtes HTTP avec reprise automatique (backoff exponentiel) et pagination Hub'Eau gérée (paramètres `size` / `page`, limite de profondeur de résultats à respecter en découpant par station ou par période).
- Chaque étape est idempotente : relancer le job sur la même semaine donne le même résultat.
- Une source indisponible ne bloque pas les autres ; l'indice composite est calculé avec les composantes disponibles et signalé comme partiel.

### 7.3 Traitement Sentinel-2 [V2]

1. Recherche STAC sur l'emprise du département (tampon de 1 km), couverture nuageuse de la scène < 80 %.
2. Chargement par `odc-stac` directement reprojeté en EPSG:2154, grille de 10 m alignée sur une grille fixe du projet.
3. Masquage à partir de la couche SCL : ne garder que les classes 4 (végétation), 5 (sol nu), 6 (eau) et 7 (non classé) ; exclure 0, 1, 2, 3, 8, 9, 10, 11.
4. Calcul NDVI et NDMI.
5. Composite médian sur 10 jours (décades), avec le nombre d'observations valides par pixel comme bande de qualité.
6. Anomalie par rapport à la référence de la même décade.
7. Écriture en COG (entier 16 bits, facteur d'échelle 10 000, compression DEFLATE, prédicteur 2, aperçus internes).
8. Enregistrement dans `rst.produit`.
9. Agrégation zonale par classe d'occupation du sol et par zone, écrite dans `idx.indice_zone`.

---

## 8. Restitution

### 8.1 API (FastAPI)

- `GET /zones` : zones avec géométrie et dernier indice composite (GeoJSON).
- `GET /zones/{zone_id}/series?indice=&debut=&fin=` : séries hebdomadaires.
- `GET /stations?source=` : stations avec dernier indice (GeoJSON).
- `GET /stations/{station_id}/series` : chronique brute + indice.
- `GET /semaines/{semaine}/synthese` : synthèse départementale d'une semaine.
- TiTiler monté sur `/tiles` pour servir les COG [V2].

### 8.2 Dashboard web

- Carte MapLibre : zones colorées selon l'indice composite (7 classes), stations en surimpression, sélecteur de semaine.
- Panneau latéral : séries temporelles de la zone ou de la station sélectionnée, comparées à la normale (enveloppe min / médiane / max de la référence).
- [V2] Couches raster NDVI / anomalies via TiTiler, avec curseur temporel.
- Choix de pile front à confirmer (voir §10).

### 8.3 QGIS

- Projet `qgis/secheresse_<slug>.qgz` versionné, connecté à PostGIS (connexion par service `pg_service.conf`, sans mot de passe dans le projet), généré par le script PyQGIS `qgis/construire_projet.py` à partir de `config/` et des vues `carto` : groupe « Dernière semaine », groupe « Historique » parcouru par le contrôleur temporel (pas d'une semaine), référentiels, fond OpenStreetMap.
- Styles QML versionnés dans `qgis/styles/`, reprenant la palette des 7 classes (couleurs du BSH, définies dans `config/classes.yaml` et partagées avec le dashboard).
- Rasters COG chargés depuis `rasters/`.
- Couches de fond : OSM, mosaïque EOX `s2cloudless`, WMS Copernicus Data Space (configuration personnelle).

---

## 9. Phase V0 : spikes de validation

À réaliser avant tout développement structurant. Chaque spike produit un court compte rendu dans `docs/spikes/`.

1. **SIM Météo-France** : délai entre la date des données et leur disponibilité ; format exact des fichiers ; identifiant des mailles couvrant la Vendée.
2. **Hub'Eau** : profondeur d'historique réelle des chroniques piézométriques et des `QmnJ` sur les stations de Vendée ; comportement de la pagination sur un gros volume.
3. **Période de référence** : nombre de stations disposant d'au moins 15 ans de données, par zone.
4. **Sentinel-2** : chargement d'une décade estivale sur la Vendée avec `odc-stac`, temps de traitement, taille du COG obtenu, part de pixels valides.
5. **DVC + DagsHub** : `dvc push` / `dvc pull` d'un Parquet test.

---

## 10. Pile technique

| Rôle | Choix |
|---|---|
| Langage | Python 3.12, gestion d'environnement avec `uv` |
| Données tabulaires | pandas / geopandas, pyarrow (GeoParquet) |
| Raster [V2] | xarray, rioxarray, odc-stac, pystac-client, planetary-computer, rasterio, dask |
| Statistiques | scipy (lois gamma pour le SPI), numpy |
| HTTP | httpx + tenacity |
| Base de données | PostGIS (image `postgis/postgis`, Docker Compose), SQLAlchemy + GeoAlchemy2, migrations Alembic |
| API | FastAPI, TiTiler |
| Front | **À confirmer** : React + MapLibre GL JS + bibliothèque de graphiques (proposition), ou prototype Streamlit pour la V1 |
| Versionnage données | DVC, remote DagsHub |
| Tests | pytest, avec réponses API enregistrées (fixtures) pour ne pas dépendre du réseau |
| Qualité | ruff, mypy sur le code du pipeline |

---

## 11. Arborescence cible

```
observatoire-secheresse/
├── CLAUDE.md
├── README.md
├── docs/
│   ├── SPEC.md                  # ce document
│   ├── methodologie.md
│   └── spikes/
├── config/
│   ├── projet.yaml              # territoire (département, slug), CRS, chemins
│   ├── classes.yaml
│   ├── sources.yaml             # points d'accès des API
│   ├── zones.yaml               # zones et pondérations (propre au territoire)
│   └── nomenclature_ocs.yaml    # [V2]
├── pipeline/
│   ├── sources/                 # un module par source (piezo, hydro, onde, meteo, s2)
│   ├── indices/                 # spi, ips, debit, onde, composite
│   ├── reference/               # calcul ponctuel des normales
│   ├── raster/                  # [V2]
│   ├── db/                      # chargement PostGIS (db-rebuild), migrations Alembic (db/migrations/)
│   └── run_hebdo.py
├── api/
├── dashboard/
├── qgis/
│   ├── construire_projet.py     # génération du projet (PyQGIS)
│   ├── secheresse_<slug>.qgz
│   └── styles/
├── data/                        # suivi par DVC
├── rasters/                     # local, ignoré
├── tests/
├── docker-compose.yml
├── Makefile
├── .env.example
└── pyproject.toml
```

---

## 12. Critères d'acceptation de la V1

1. `make ingest` récupère l'historique complet des stations de Vendée pour les trois réseaux Hub'Eau et les données SIM, et écrit les GeoParquet.
2. `make reference` calcule les normales et les enregistre.
3. `make hebdo` exécute le job de la dernière semaine ISO complète de bout en bout, y compris `dvc push`.
4. `make db-rebuild` reconstruit PostGIS à l'identique à partir des seuls Parquet.
5. Les indices SPI, IPS et débit sont calculés pour chaque station éligible et agrégés par zone ; l'indice composite est disponible pour chaque zone.
6. L'API expose les endpoints du §8.1 (hors TiTiler).
7. Le dashboard affiche la carte des zones pour une semaine choisie et les séries d'une zone ou d'une station.
8. Le projet QGIS s'ouvre et affiche les couches PostGIS avec leurs styles.
9. Les tests passent sans accès réseau.
10. Relancer deux fois le job sur la même semaine produit des résultats identiques.

---

## 13. Risques et points ouverts

| Sujet | Risque / question | Piste |
|---|---|---|
| Latence SIM | Données trop tardives pour un suivi hebdomadaire | Levé par le spike V0 n°1 : délai d'un jour |
| Couverture piézométrique | Peu de piézomètres sur le socle, publication par lots | Poids faible de l'IPS dans le bocage, critère de fraîcheur (méthodologie, D1 et D2) |
| Corrections a posteriori | Indices qui changent rétroactivement | Fenêtre de réingestion de 90 jours, tags DVC hebdomadaires |
| Nuages (Sentinel-2) | Composites incomplets | Décades au lieu de semaines, bande de qualité, seuil minimal de pixels valides |
| Historique court de sécheresses | Surapprentissage en V4 | Méthodes simples (régressions, analogues) avant tout modèle d'apprentissage |
| Population présente (V3) | Pas de donnée mensuelle ouverte par commune | Estimation résidents + résidences secondaires + lits touristiques × taux d'occupation mensuel |
| Front | Pile non arrêtée | Décision avant le début du développement du dashboard |
| Modèle d'occupation du sol | Nomenclature et format à fixer | Respect du contrat d'interface du §4.7 |
