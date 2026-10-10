# Passation — Observatoire de la sécheresse (Vendée)

État au **2026-10-10**. Ce document permet de reprendre le projet dans une nouvelle conversation, sans l'historique des échanges. À lire avec [`CLAUDE.md`](CLAUDE.md) (règles du projet), [`docs/SPEC.md`](docs/SPEC.md) (référence) et [`docs/methodologie.md`](docs/methodologie.md) (décisions D1 à D9, qui priment sur la spec).

## 1. En bref

- **Objectif** : suivi hebdomadaire de la sécheresse en Vendée, **par zone hydrogéologique** (12 zones), à partir de la pluie (SIM), des nappes, des débits, des observations ONDE et du remplissage des retenues. Chaque variable est comparée à sa normale 1991-2020, convertie en valeur standardisée classée sur 7 niveaux, puis combinée par zone en un **indice composite** pondéré. Le code est générique : un autre département se configure dans `config/`.
- **Avancement** : V0 (spikes) et **V1 terminées**, tous les critères d'acceptation de la V1 remplis (SPEC §12). Le premier `make hebdo` complet a tourné le 2026-10-06 (commit « Données 2026-W40 », étiquette `data-2026-W40`). Depuis : version publique du dashboard sur GitHub Pages, licences, README et feuille de route.
- **Prochaine étape** : **valider l'indice sur les sécheresses passées** (section 7.1). C'est la condition pour le présenter aux acteurs (DDTM 85, Vendée Eau, syndicats de bassin).
- **Où voir les résultats** : dashboard public <https://baptistefeldmann.github.io/observatoire-secheresse/> (semaine 2026-W40 au 2026-10-10) ; en local, <http://localhost:8010/dashboard/> après `make up` ; QGIS par le tunnel SSH.
- **Dépôts** : code sur GitHub [`baptistefeldmann/observatoire-secheresse`](https://github.com/baptistefeldmann/observatoire-secheresse) (public, branche `main`, site sur la branche `gh-pages`) ; données sur DagsHub (remote DVC `origin`, `https://dagshub.com/baptistefeldmann/observatoire-secheresse.dvc`).

## 2. Façon de travailler avec l'utilisateur

Préférences constantes, à respecter dès la première réponse :

- **Commits** : Claude prépare et indexe (`git add`) ; **l'utilisateur committe et pousse lui-même**, à partir des commandes que Claude lui donne (blocs `bash` séparés, message en français, ligne `Co-Authored-By`). Jamais de `git commit`, `git push`, `dvc push`, ni de `make hebdo` avec publication ou de `make pages` lancés par Claude. Seule exception voulue : `make hebdo`, lancé par l'utilisateur, committe et pousse lui-même les `data/*.dvc` et l'étiquette de la semaine.
- **Décisions** : pour tout choix de méthode, de schéma, de pile ou de source, **expliquer simplement les options, les chiffrer sur les vraies données, recommander, puis demander** (outil de questions fermées). L'utilisateur pose des questions de fond et repère lui-même des anomalies dans les données (non-stationnarité vue dans QGIS).
- **Le portable Windows ne sert qu'à consulter** : tunnel SSH + QGIS 3.44.8 + navigateur. Rien à cloner, installer ou copier dessus. Tout est généré **et testé sur la machine Linux** (QGIS en Docker, Chromium sans interface pour le dashboard) puis servi par PostGIS ou l'API.
- **Vérifier soi-même** avant de livrer : sorties confrontées aux vraies données (effectifs, dates, doublons, idempotence), captures d'écran des rendus (QGIS, dashboard, schémas, PDF).
- **Exports PDF** : l'organisation de l'utilisateur bloque l'export PDF du service de documents. Les PDF sont générés en local (HTML + Chromium) et déposés dans `/media/lfrn1dgt04/D/baptiste` (partage réseau).
- Langue : français, phrases courtes, pas de jargon non expliqué.

## 3. Environnement

| Élément | Valeur |
|---|---|
| Machine | Linux, `/home/bfeldmann/projects/hydrolyse_dashboard`, 8 cœurs, 31 Go de RAM, fuseau Europe/Paris |
| Python | 3.12 via `uv`. **Toujours `uv sync --extra raster`** : un `uv sync` simple désinstalle les paquets Sentinel-2 (xarray, odc-stac…) |
| Conteneurs | `make up` démarre `secheresse_vendee-postgis-1` (PostGIS 16-3.4, port **5433**) et `secheresse_vendee-api-1` (port **8010**), tous deux limités à `127.0.0.1`. Pas de redémarrage automatique : `make up` après un redémarrage de la machine ou un `make down`. Le volume `secheresse_vendee_pgdata` conserve la base (1,45 Go) |
| Images Docker | `secheresse_vendee-api` (982 Mo, construite par `make up`) ; `qgis/qgis:3.44.8` (2,2 Go, pour `make qgis`) |
| Ports déjà pris sur la machine | 5432 (`pg_container`), 8000 (`mlops_meteo_australie-nginx-1`) |
| Secrets | `.env` (non versionné) : `POSTGRES_PASSWORD`, `POSTGRES_LECTEUR_PASSWORD`, `DAGSHUB_USER`, `DAGSHUB_TOKEN` ; `make dvc-auth` copie DagsHub dans `.dvc/config.local`. Clé SSH GitHub sans phrase de passe (utilisée par `make hebdo` et `make pages`) |
| Accès distant | portable Windows → tunnel `ssh -N secheresse-tunnel` (ports 5433 et 8010), service PostgreSQL `secheresse_vendee`, rôle `lecteur`, `PGSERVICEFILE` et `pgpass.conf` en place. Procédure : [`docs/acces_distant.md`](docs/acces_distant.md) |
| Outils de vérification | Playwright + Chromium étaient installés dans le dossier temporaire de la session : à réinstaller (`npm i playwright && npx playwright install chromium` dans un dossier temporaire) pour refaire des captures du dashboard |

## 4. Commandes

```
make up            # démarre PostGIS et l'API (port 8010), reconstruit l'image de l'API si besoin
make down          # arrête les deux (la base est conservée)
make config        # valide et affiche la configuration du territoire
make referentiels  # communes, zones, mailles SIM, stations -> data/referentiels/ (~1 min)
make ingest        # référentiels + historique complet -> data/raw/ (~10 min)
make reference     # normales, enveloppes, ruptures -> data/normales/ (~20 s)
make indices       # indices 1991 -> dernière semaine complète -> data/indices/ (~25 s)
make db-rebuild    # recharge PostGIS depuis data/ en une transaction (~1 min)
make hebdo         # job hebdomadaire complet, publication comprise (~3 min) ; rapport dans logs/hebdo/
make qgis          # projet QGIS (QGIS en Docker) -> qgis/ et PostGIS (~20 s)
make site          # dashboard statique -> build/pages (~80 s, ~100 Mo ; PostGIS démarré)
make pages         # make site puis remplace la branche gh-pages (pousse sur GitHub)
make test          # 102 tests sans réseau ni service (à lancer aussi PostGIS arrêté)
make test-db       # 19 tests d'intégration sur une base PostGIS jetable (Docker, port 55433)
make lint          # ruff + mypy strict (pipeline, api, tests)
```

Variantes : `uv run python -m pipeline hebdo --sans-publication` (ni DVC ni Git) ; `uv run python -m pipeline indices --debut AAAA-Www --fin AAAA-Www`. **Routine hebdomadaire actuelle** (manuelle, pas de cron) : `make up`, `make hebdo`, puis `make pages` pour mettre à jour le site public.

## 5. Ce qui a été fait

### 5.1 V0 — Spikes (comptes rendus dans `docs/spikes/`)

| Spike | Conclusion |
|---|---|
| n°1 SIM Météo-France | délai d'**un jour** (fichier quotidien publié vers 10 h, heure de Paris) ; aucune autre source météo nécessaire ; grille de 8 km en Lambert II étendu ; 145 mailles pour la Vendée |
| n°2-3 Hub'Eau | historique long (piézo depuis 1985, débits depuis 1965) ; **aucun piézomètre vendéen en temps réel**, publication par lots (11 jours à 7 mois de retard) ; `profondeur_nappe` est une copie du niveau NGF ; ONDE seulement depuis 2012 |
| n°4 Sentinel-2 | via **Planetary Computer** (choix utilisateur) ; une décade en 3 à 5,5 min ; **offset BOA de −1000 indispensable** ; environ 12 Go de rasters par an ; rasters du spike conservés dans `rasters/spike_v0/` (313 Mo) |
| n°5 DVC + DagsHub | aller-retour push/pull validé |
| n°6 Retenues | table ArcGIS publique du Département (13 retenues de Vendée Eau, hebdomadaire depuis 2019) ; repli sur la couche nationale de la DREAL Bretagne |

### 5.2 V1 — Les neuf étapes

| # | Étape | Où | Résultat |
|---|---|---|---|
| 1 | Référentiels | `pipeline/referentiels.py`, `zonage.py`, `sources/` | 253 communes, **12 zones** (D5), 145 mailles SIM, 140 stations (56 piézomètres, 41 hydrométriques, 30 ONDE, 13 retenues) rattachées à leur zone |
| 2 | Ingestion | `pipeline/ingestion.py`, `stockage.py` | un fichier par source et par année dans `data/raw/` ; fusion idempotente (valeur inchangée = date d'ingestion conservée ; valeur corrigée = remplacée) ; station en échec consignée sans bloquer |
| 3 | PostGIS | `pipeline/db/` (Alembic) | schémas `ref`, `obs`, `idx`, `rst` ; `make db-rebuild` en une transaction (COPY) ; reconstruction à l'identique vérifiée par empreinte |
| 4 | Normales | `pipeline/reference/` | SPI 1, 3, 6 mois par zone (loi gamma, 1 872 normales), IPS pour 37 piézomètres, indice de débit pour 29 stations ; test de rupture (Pettitt) ; enveloppes min/médiane/max (ajoutées à l'étape 8) |
| 5 | Indices de la semaine | `pipeline/indices/` (D9) | SPI par zone, IPS et débit par station (rang de Gringorten), ONDE par campagne, indices de zone, composite à poids renormalisés ; historique 1991-W01 → 2026-W40 (environ 91 700 indices de station, 97 300 de zone, 22 400 composites) |
| 6 | Job hebdomadaire | `pipeline/run_hebdo.py`, `publication.py` | ingestion des 90 derniers jours (piézomètres : depuis leur dernière mesure en stock), recalcul de tout l'historique, contrôles de vraisemblance, DVC + commit des seuls `data/*.dvc` + étiquette `data-AAAA-Www` + push, rechargement de PostGIS, rapport `logs/hebdo/AAAA-Www.md` |
| 7 | Projet QGIS | `qgis/construire_projet.py`, vues `carto.*` | projet généré par QGIS 3.44.8 en Docker, rangé dans PostGIS (`carto.qgis_projects`), ouvert depuis le portable par Projet › Ouvrir depuis › PostgreSQL ; groupes « Dernière semaine », « Historique » (contrôleur temporel), « Référentiels », « Fond » ; styles QML dans `qgis/styles/` ; **rendu validé par l'utilisateur** |
| 8 | API | `api/app.py`, `requetes.py`, `Dockerfile` | FastAPI en service Docker, rôle `lecteur`, port 8010 ; les 5 points d'accès du §8.1 plus `/`, `/classes`, `/semaines`, `/sante` ; GeoJSON WGS84, contours simplifiés à 20 m ; documentation sur `/docs` |
| 9 | Dashboard | `dashboard/` (servi par l'API sous `/dashboard/`) | MapLibre 6 + ECharts 6 sans framework ; fond Plan IGN ; carte des zones et des stations par semaine, chiffres clés, synthèse, séries de zone et de station avec l'enveloppe de la normale, tableau sous chaque graphique, lien partageable ; **validé par l'utilisateur** |

Migrations PostGIS : `0001` schéma initial, `0002` colonnes des indices, `0003` vues `carto`, `0004` table des projets QGIS, `0005` enveloppes des normales.

### 5.3 Après la V1

| Réalisation | Détail |
|---|---|
| Version publique du dashboard | `api/export.py` exporte les réponses de l'API en fichiers (environ 97 Mo) ; le dashboard les lit quand `window.OBSERVATOIRE.statique` est défini ; bandeau « prototype en cours de validation » et balise `noindex` (texte et sources dans `config/projet.yaml`, bloc `publication`) ; `make pages` remplace la branche `gh-pages` par un commit orphelin. En ligne depuis le 2026-10-07 |
| Document de méthodologie | « Méthodologie des normales et de l'indice composite » : document Claude Docs privé (<https://claude.ai/code/artifact/d49d372c-7fa7-4724-b9d5-d456e236edd9>) et PDF de 6 pages dans `/media/lfrn1dgt04/D/baptiste/Methodologie_normales_indice_composite_2026-10-07.pdf`. Le PDF ne suit pas les modifications du document : à régénérer si besoin |
| README | réécrit : présentation, architecture, installation, utilisation, base, QGIS, API et dashboard, adaptation à un autre département, arborescence, feuille de route (section 10), licence (section 11) |
| Feuille de route | schéma [`docs/roadmap.svg`](docs/roadmap.svg) (fond blanc, lisible en thème sombre) : à mettre à jour à la fin de chaque phase |
| Licences | code sous **MIT** (`LICENSE`, aussi dans `pyproject.toml`) ; données produites (indices, normales, zones) sous **Licence Ouverte 2.0** ; données des fournisseurs sous leurs propres conditions ; relevés des retenues exclus ([`LICENCE-DONNEES.md`](LICENCE-DONNEES.md)) |

## 6. Choix effectués

### 6.1 Décisions de méthode (détail et chiffres dans `docs/methodologie.md`)

| Id | Décision |
|---|---|
| D1 | Un piézomètre n'entre au composite que si sa dernière mesure a moins de 45 jours ; affiché sinon, et sans indice après un an sans mesure |
| D2 | IPS pondéré à 0,15 dans le bocage (nappes de socle peu suivies, redondantes avec les débits) |
| D3 | ONDE affiché à part, **hors composite** (historique trop court pour une normale) |
| D4 | Raccordement des stations hydrométriques successives d'un même site (Sèvre nantaise à Tiffauges seulement) |
| D5 | 12 zones = unions de masses d'eau souterraine (SANDRE), croisées avec les zones d'alerte (SANDRE `ZAS`) dans le bocage |
| D6 | Retenues d'eau potable : source ajoutée, affichée hors composite, comparées aux mêmes semaines depuis 2019 |
| D7 | Normales : critère **par période** (mois valide à 10 jours de mesures ; Q7 à 5 jours sur 7, fenêtre de ±15 jours) ; 1991-2020 si 15 ans valides, sinon toutes les années avec avertissement ; SPI sur la **pluie moyenne de la zone** |
| D8 | Ruptures de fonctionnement : détection automatique (Pettitt), traitement d'une liste **validée à la main** (`config/stations.yaml`) ; normale limitée au nouveau régime dès 8 ans. 7 piézomètres traités (marais breton depuis 2011 ou 2016, Noirmoutier depuis 2021, sans IPS avant 2028) |
| D9 | Indices de la semaine : IPS sur le **mois en cours** s'il a 10 jours de mesures, sinon le dernier mois valide ; rang de **Gringorten** ; SPI borné à ±3 ; indice de zone = moyenne des stations retenues ; composite à poids renormalisés ; `version_methodo` = « D9 » |

Pondérations du composite (`config/zones.yaml`, SPI 3 mois / IPS / débits) : Sud-Vendée 0,25 / 0,50 / 0,25 ; marais 0,30 / 0,40 / 0,30 ; îles 0,40 / 0,60 / 0 ; bocage 0,40 / 0,15 / 0,45.

### 6.2 Choix techniques faits par l'utilisateur

| Sujet | Choix | Alternative écartée |
|---|---|---|
| Sentinel-2 (V2) | Planetary Computer | Copernicus Data Space |
| Colonnes des indices | colonnes dédiées (`date_mesure`, `hors_reference`, `dans_composite`, `detail`) | une colonne JSON unique |
| Publication du job | automatique (DVC, commit des `.dvc`, étiquette, push) | DagsHub seul, ou rien |
| Lots piézométriques | fenêtre d'ingestion par station, depuis la dernière mesure en stock | 90 jours partout |
| Planification | **pas de cron** pour l'instant (ligne prête dans le README, lundi 11 h) | cron le lundi |
| Palette des 7 classes | couleurs du BSH (vert pour « normal »), dans `config/classes.yaml` | brun, blanc, bleu |
| Semaine dans QGIS | vues PostGIS `carto.*` (dernière semaine + contrôleur temporel) | requêtes dans le projet |
| Projet QGIS | généré en Docker sur la machine Linux, **rangé dans PostGIS** | script dans le QGIS du portable (abandonné après un essai raté) |
| Base en fichier | rien : la base persiste dans le volume Docker, `make down` / `make up` suffisent | export GeoPackage |
| API | service Docker démarré par `make up` | `make api` au premier plan |
| Normales pour l'API | table `idx.enveloppe_station`, calculée par `make reference` | lecture des Parquet par l'API |
| Pile du dashboard | MapLibre + ECharts sans framework, servi par l'API | React (Vite), Streamlit |
| Fond de carte | Plan IGN (Géoplateforme) | OpenStreetMap, aucun |
| GitHub Pages | publier tout de suite avec bandeau et `noindex` ; retenues conservées ; publication manuelle (`make pages`) | attendre la validation ; retirer les retenues ; publier dans `make hebdo` |
| Wiki GitHub | non (la roadmap reste dans le dépôt) ; suggestion faite d'Issues et de jalons, non décidée | roadmap dans le Wiki |
| Licences | MIT pour le code, Licence Ouverte 2.0 pour les données produites | Apache 2.0, EUPL 1.2 ; CC BY 4.0 |

## 7. Ce qu'il reste à faire

### 7.1 Prochaine étape : valider l'indice

À faire avant toute présentation aux acteurs. Démarrer par une proposition de protocole chiffrée, à soumettre à l'utilisateur.

- **Confronter les classes** de 2011, 2017, 2019 et 2022 aux arrêtés de restriction (VigiEau, historique des arrêtés) et au bulletin de situation hydrologique. Exemple qui motive la validation : la semaine du 15 août 2022, seules 6 zones sur 12 sont en classe 1 ou 2.
- **Trancher la rareté des classes extrêmes** dans les moyennes par zone : composite en classe 1 de 5,4 % (marais breton) à 11,8 % (Noirmoutier) du temps sur 1991-2020, pour 10 % attendus ; IPS de zone du Sud-Vendée en classe 1 4 % du temps. Pistes : restandardiser l'indice de zone et le composite sur leur propre historique, ou documenter l'effet. Toute modification = nouvelle décision D10 et `version_methodo` à changer.
- **Vérifier les pondérations** du marais et du Sud-Vendée : elles viennent de la spécification d'origine, sans justification chiffrée.
- **Ruptures** : documenter l'origine des ruptures de Noirmoutier et du marais breton (BRGM, gestionnaires) ; trancher les deux ruptures signalées et non traitées (05342X0073/F, jugée faux positif ; 05863X0203/F, +0,3 m en 2010) ; examiner le piézomètre **05634X0013/SF3** (bocage Sèvre nantaise, seul piézomètre de sa zone), « haut » sur 2020-2022 sécheresse comprise, écart de +2,2 m non significatif au test.

### 7.2 Exploitation

- Planifier le job (cron le lundi 11 h, après la publication du SIM) — refusé pour l'instant par l'utilisateur.
- Intégration continue GitHub Actions (lint + tests) : proposée, non faite.
- `restart: unless-stopped` pour PostGIS et l'API : proposé, non appliqué.
- Alléger l'image de l'API (982 Mo, toutes les dépendances du pipeline).
- `make hebdo` : son `git push` envoie aussi les commits locaux non poussés de `main` ; une semaine recalculée après correction déplace son étiquette (`push --force` de l'étiquette seule).

### 7.3 Données et sources

- **Retenues, qualité de la source** : relevés en dents de scie (Albert : 31 %, 63 %, 28 % trois semaines de suite en janvier 2025 ; 66 sauts de plus de 10 points pour Albert, 67 pour Pierre-Brune). Transferts ou erreurs de saisie : à éclaircir si l'indicateur doit être exploité finement. Source ArcGIS fragile (nom de service changeant, suffixe `_TEST`). L'utilisateur ne souhaite pas contacter Vendée Eau pour l'instant.
- **Retenues, licence** : aucune licence publiée ; publiées sur le site public par choix de l'utilisateur ; à retirer si le Département le demande (filtre dans `api/export.py`).
- **Licences des fournisseurs** : Météo-France (SIM) et SANDRE vérifiées (Licence Ouverte 2.0) ; Hub'Eau et IGN à confirmer sur leurs sites.
- **Titularité des droits** du code (MIT au nom de Baptiste Feldmann) : à vérifier si le projet relève du cadre professionnel de l'utilisateur (Siradel).
- **Raccordements non retenus** : Yon (Nesmy / Chaillé, 5 jours communs ; possible avec un ajustement par surface de bassin), Boulogne.
- **Dépôt public** : nécessaire pour GitHub Pages sans offre payante ; le site porte `noindex`, le dépôt reste indexable.

### 7.4 Phases suivantes (SPEC §2, ne pas commencer sans demande explicite)

- **V2** : composites Sentinel-2 par décade (NDVI, NDMI), anomalies par rapport à 2018-2025, carte d'occupation du sol interne, anomalies par classe ; seuil minimal d'observations valides ; écriture par blocs (RAM) ; 12 Go par an dans `rasters/` ; TiTiler sur `/tiles`.
- **V3** : axe pression (population présente par commune et par mois, prélèvements BNPE, surfaces irriguées, réserves de substitution du Marais poitevin) et carte de tension ; place naturelle des retenues.
- **V4** : prévision (nappes à 1-2 mois, années analogues, demande saisonnière).

## 8. Erreurs et problèmes rencontrés

Les leçons à retenir sont en gras. Plusieurs défauts n'ont été trouvés qu'en confrontant le code aux **vraies données** ou en **regardant le rendu** : garder cette pratique.

### 8.1 Données et méthode

| Étape | Problème | Correction |
|---|---|---|
| Zonage | Fichier VigiEau « en vigueur » pris pour le référentiel des zones d'alerte (il ne contient que les zones sous arrêté du jour) ; 7,9 Go téléchargés pour rien | référentiel SANDRE `ZAS`. **Vérifier la taille d'une ressource avant de la télécharger** |
| Retenues | Numéros de semaine de la source non ISO (26 % d'écarts) ; table du total décalée d'une semaine | semaine déduite de la date ; total recalculé par somme |
| Retenues | Couche nationale : géométries `MultiPoint`, chaînes vides, 4,1 × 10⁶ = 4 099 999,999… | toute géométrie ponctuelle acceptée, chaînes vides = manquantes, arrondi au m³ |
| Ingestion | ONDE : code de campagne entier d'un côté, texte de l'autre ; jointure vide sans erreur | conversion en texte des deux côtés |
| Ingestion | **Défaut grave** : avec les types nullables de pandas, `<NA> == "x"` vaut `<NA>`, lu comme une égalité ; une valeur complétée à la source n'aurait jamais été mise à jour | `fillna(False)` + test. **Se méfier des comparaisons avec les types nullables** |
| Ingestion | Observations ONDE de stations hors référentiel : clé étrangère cassée en base | filtrage à l'ingestion |
| Normales | **Non-stationnarité ignorée au départ** : 9 piézomètres sur 38 ont changé de régime ; L'Épine aurait été « très haut » en permanence. Repéré par l'utilisateur dans QGIS | D8 |
| Normales | Plantage sans données suffisantes | tables vides au bon schéma |
| Indices | Recalcul partiel différent du calcul complet (écart de 10⁻¹⁷) : ordre de sommation variable | tri par station avant la moyenne. **Pour l'idempotence au bit près, fixer l'ordre des sommes** |
| Job hebdo | La fenêtre de 90 jours de la spec aurait perdu les lots piézométriques (8 piézomètres sur 39 sans mesure depuis plus de 90 jours) | fenêtre par station |
| Job hebdo | Premier run : Hub'Eau avait corrigé 23 débits (N322201010, juillet-septembre) | comportement voulu : le recalcul complet les répercute sur les semaines 27 à 36 |

### 8.2 Infrastructure et code

| Étape | Problème | Correction |
|---|---|---|
| Squelette | Healthcheck PostGIS « prêt » pendant l'initialisation ; port ouvert sur toutes les interfaces | `pg_isready -h 127.0.0.1` ; port limité à `127.0.0.1` |
| Accès distant | Même alias SSH pour Git et le tunnel | deux entrées `secheresse` et `secheresse-tunnel` |
| Spike Sentinel-2 | Nodata −32767 au lieu de −32768 ; nombre d'observations dupliqué en int16 | écrêter puis remplir ; COG de qualité séparé en uint8 |
| Vérification | `md5sum -c` affiche « Réussi » en locale française : contrôle mal lu | `LC_ALL=C` |
| Projet QGIS | Script prévu pour le QGIS du portable : clone nécessaire, et un copier-coller dans la console a fait chercher `config/` dans un dossier temporaire | génération en Docker sur la machine Linux, projet rangé dans PostGIS. **Tester soi-même plutôt que faire tester l'utilisateur** |
| API | Colonnes `jsonb` décodées deux fois (erreur 500) ; arrondis `numeric` renvoyés en texte (`"40.0"`) | pas de `json.loads` sur du `jsonb` ; `::float8` après `round` |
| API | Tests « paramètres invalides » qui ouvraient une connexion : ils ne passaient que PostGIS démarré | connexion factice. **Lancer `make test` aussi PostGIS arrêté** |
| Dashboard | MapLibre 6 n'est publié qu'en module ES (pas de `maplibre-gl.js`, pas de variable globale) | `import * as maplibregl from ".../maplibre-gl.mjs"` |
| Dashboard | Défauts vus sur les captures : île d'Yeu sous la légende, mois en anglais, crues écrasant les étiages, légende incomplète, « null » affiché, ordre des modalités ONDE (clés numériques d'un objet JS triées d'abord) | marges de cadrage, axes en français, débits en échelle log, `Map` pour l'ordre. **Regarder le rendu avant de livrer** |
| Environnement | `uv sync` sans option a désinstallé les paquets Sentinel-2 | `uv sync --extra raster` |
| Shell | `pkill -f "<motif>"` a tué le shell qui le lançait (le motif figurait dans sa propre ligne de commande, code 144) | motif à crochets (`"[u]vicorn"`) et commande `pkill` lancée seule |

## 9. Repères dans le code

| Besoin | Fichier |
|---|---|
| Paramètres du territoire, seuils, pondérations | `config/projet.yaml`, `zones.yaml`, `classes.yaml`, `stations.yaml`, `sources.yaml` ; modèles dans `pipeline/config.py` |
| Point d'entrée du pipeline | `pipeline/__main__.py` (`python -m pipeline <commande>`) |
| Une source de données | `pipeline/sources/<source>.py` |
| Normales / indices | `pipeline/reference/`, `pipeline/indices/` |
| Schéma de la base | `pipeline/db/migrations/versions/0001…0005` ; chargement dans `pipeline/db/chargement.py` |
| Job hebdomadaire | `pipeline/run_hebdo.py`, `pipeline/publication.py` |
| API, export statique | `api/app.py`, `api/requetes.py`, `api/export.py`, `api/Dockerfile` |
| Dashboard | `dashboard/index.html`, `app.js`, `style.css` |
| Projet QGIS | `qgis/construire_projet.py` |
| Tests | `tests/` (fixtures enregistrées dans `tests/fixtures/`) |

## 10. Contexte utile

- **Existant** : Info-Sécheresse (imaGeau) classe déjà nappes, débits et pluie sur 7 niveaux, chaque jour ; la DDTM 85 publie un bulletin hebdomadaire en période de tension. La valeur ajoutée du projet : la **lecture par les 12 zones vendéennes**, un **indice composite à méthode publiée**, le **satellite par type d'occupation du sol** (V2) et la **réplicabilité**.
- **94 % de l'eau potable vendéenne vient des retenues** : l'indicateur le plus suivi localement. Au 2026-09-27, remplissage total de 35,6 %, sous le minimum des semaines 39 de 2019-2025 (37,5 %).
- **2026 est une année très sèche** dans les données : 101 des 142 SPI bornés à ±3 depuis 1991 sont de 2026 ; 9 zones sur 12 en classe 1 en semaine 40.
- **Stockage** : `data/` pèse 20 Mo (versionné sur DagsHub) ; `.venv` 938 Mo ; `rasters/spike_v0/` 313 Mo (conservé à la demande de l'utilisateur) ; site statique `build/pages/` environ 100 Mo (non versionné).
