# Spike V0 n°1 — Données SIM de Météo-France

Date : 2026-09-30 · Département : 85 · Script : [`sim_meteo.py`](sim_meteo.py)

## Questions

1. Délai entre la date des données SIM et leur mise à disposition. Un complément par stations ou par l'API Météo-France est-il nécessaire (§4.4, §13) ?
2. Format exact des fichiers.
3. Identifiant des mailles couvrant le territoire.

## Source

Jeu data.gouv.fr « Données changement climatique - SIM quotidienne » (`6569b27598256cc583c917a7`, paramètres dans `config/sources.yaml`). Il est hébergé par Météo-France sur un stockage objet OVH, sans authentification.

| Ressource | Contenu | Taille | Mise à jour |
|---|---|---|---|
| `QUOT_SIM2_<annee>.csv.gz` | une année, toute la métropole, de 1958 à l'année en cours | 100 à 140 Mo | bimensuelle pour les 4 dernières années |
| `QUOT_SIM2_latest.csv.gz` | 60 jours glissants | 20 Mo | quotidienne |
| `SHP_SIM_FRANCE.*` | points de grille avec `num_maille`, département, lat/lon (sans `.prj`) | 2 Mo | |
| `SIM_QUOTIDIENNE_parametres.pdf` | définition et unités des variables | | |

Le shapefile `SIM2.*` est inutilisable : pas de `.dbf`, et GDAL ne le lit pas.

## Résultats

### 1. Délai : 1 jour

Le 30/09, `QUOT_SIM2_latest` contient les données jusqu'au **29/09**. Le fichier annuel 2026 s'arrête au 26/09.

**Un complément par stations ou par l'API Météo-France n'est pas nécessaire.** Le risque « Latence SIM » du §13 est levé, et `METEOFRANCE_API_KEY` devient inutile en V1.

### 2. Format

- CSV séparé par `;`, compressé en gzip, une ligne par point de grille et par jour, 29 colonnes.
- `DATE` au format `AAAAMMJJ`.
- `LAMBX` et `LAMBY` : centre de la maille en **Lambert II étendu (EPSG:27572), en hectomètres**. Il faut multiplier par 100 pour obtenir des mètres. La conversion concorde avec les lat/lon du shapefile à 0,001° près.
- Grille régulière de 8 km, soit 9 892 points dans le CSV et 8 981 dans le shapefile.

Variables utiles pour la V1 :

| Colonne | Contenu | Unité | Période |
|---|---|---|---|
| `PRELIQ` + `PRENEI` | précipitations liquides + solides → `precip_mm` | mm | cumul de 06 UTC à 06 UTC |
| `ETP` | évapotranspiration potentielle (Penman-Monteith FAO-56) → `etp_mm` | mm | quotidienne |
| `SWI` | indice d'humidité des sols → `swi` | **fraction**, et non % comme l'indique la notice ; peut être légèrement négative (−0,05 à 0,31 en septembre 2026) | moyenne de 06 UTC à 06 UTC |

Aucune valeur manquante sur ces variables dans les données de Vendée.

À noter : la notice ne dit pas si `DATE = J` couvre la période de J 06 UTC à J+1 06 UTC, ou de J−1 à J. Le décalage ne dépasse pas une journée, ce qui est négligeable pour des cumuls hebdomadaires ou mensuels, mais il faudra le documenter dans le module d'ingestion.

### 3. Mailles du territoire

- On construit les mailles comme des carrés de 8 km centrés sur `LAMBX`/`LAMBY` en EPSG:27572, puis on les reprojette en EPSG:2154. Elles intersectent le contour départemental (fusion des communes de geo.api.gouv.fr) élargi d'un tampon de 1 km.
- **145 mailles**, dont 106 ont plus de la moitié de leur surface dans le département.
- Elles couvrent **99,9 %** du département. Les parties non couvertes sont en mer : l'Île-d'Yeu est couverte à 82 %, Noirmoutier à 94 %.
- **Identifiant** : les 145 mailles ont un `num_maille` officiel dans `SHP_SIM_FRANCE`, qu'on retrouve par jointure sur `lambx`/`lamby`. C'est un entier, conforme à `ref.maille_safran.maille_id` (§5.3).
- Le champ `num_dep` du shapefile ne suffit pas pour la sélection. Il donne 118 mailles « 85 », alors que 12 mailles rattachées à la Loire-Atlantique et 8 aux Deux-Sèvres débordent sur la Vendée. La sélection se fait donc par géométrie, ce qui la rend identique d'un département à l'autre.

### Révisions

Sur leurs 57 jours communs (août–septembre 2026), le fichier annuel 2026 et `latest` sont **identiques** sur toutes les variables utiles. Aucune révision n'a été constatée entre la diffusion quotidienne et le fichier annuel.

La description du jeu annonce cependant une mise à jour bimensuelle des 4 dernières années. Le spike ne peut pas mesurer ces révisions sans une ancienne copie à comparer.

### Volumes et temps

- Téléchargement : 2 s pour un fichier annuel depuis la machine Linux.
- Lecture et filtrage sur les 145 mailles : 7 à 10 s par fichier.
- Extrait vendéen d'une année : environ 53 000 lignes.
- Historique 1990–2026, estimé : 37 fichiers et environ 4,5 Go de téléchargement, soit une dizaine de minutes pour moins de 2 millions de lignes, quelques dizaines de Mo en GeoParquet.

## Conséquences et propositions

| # | Constat | Proposition |
|---|---|---|
| 1 | Délai d'un jour | Pas de source météo complémentaire en V1. Corriger le §4.4 et le §13 de la spec ; retirer `METEOFRANCE_API_KEY` de `.env.example`, ou la marquer comme non utilisée |
| 2 | `latest` ne couvre que 60 jours, moins que la fenêtre de réingestion de 90 jours | Le job hebdomadaire télécharge le **fichier annuel en cours**, plus celui de l'année précédente tant que la fenêtre de 90 jours la chevauche (janvier à mars), et `latest` pour les jours manquants. Environ 250 Mo par semaine au plus, moins d'une minute |
| 3 | Grille en Lambert II étendu, en hectomètres | Construire les mailles à partir des paramètres de `config/sources.yaml` (`crs_grille`, `unite_coordonnees_m`, `pas_grille_m`), sélection par géométrie avec `emprise.tampon_m` |
| 4 | `num_maille` officiel disponible | `maille_id = num_maille`, obtenu par jointure avec `SHP_SIM_FRANCE` ; échec explicite si une maille du territoire n'en a pas |
| 5 | `SWI` en fraction | Stocker la fraction telle quelle dans `obs.meteo_jour.swi` et documenter l'unité |
| 6 | Historique de départ | Ingérer à partir de `periode_reference.hydro_meteo.debut − 1` (1990), pour que le SPI 6 mois soit calculable dès le début de la référence |
| 7 | Agrégation par zone (pour le futur module SPI) | Question de méthode à trancher au moment du SPI : standardiser par maille puis faire la moyenne par zone, ou faire la moyenne des précipitations par zone puis standardiser |
