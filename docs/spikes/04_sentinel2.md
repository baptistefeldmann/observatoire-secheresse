# Spike V0 n°4 — Composite Sentinel-2 d'une décade (Planetary Computer)

Date : 2026-09-30 · Département : 85 · Script : [`sentinel2_decade.py`](sentinel2_decade.py) · Machine : 8 cœurs, 31 Go de RAM

## Question

Charger une décade estivale sur le territoire avec `odc-stac` : temps de traitement, taille du COG obtenu, part de pixels valides (§9).

## Source

Microsoft Planetary Computer, collection `sentinel-2-l2a`, à la demande (au lieu d'Earth Search, prévu initialement). L'approche reprend le projet interne `eo_factory` : URL signées par `planetary_computer.sign`, offset BOA, `dtype`/`nodata` explicites, liste blanche SCL. Les paramètres sont dans `config/sources.yaml` (`sentinel2`).

Été 2025 sur l'emprise (département + 1 km) : 177 scènes à moins de 80 % de nuages, 4 tuiles MGRS (`30TWS`, `30TWT`, `30TXS`, `30TXT`), 3 satellites (2A, 2B, 2C). Toutes en **baseline 05.11** : l'offset BOA de −1000 s'applique à 100 % des scènes récentes.

| Décade 2025 | Scènes | Jours d'acquisition | Nuages moyens |
|---|---|---|---|
| juin 1 / 2 / 3 | 12 / 21 / 19 | 3 / 5 / 5 | 22 / 11 / 28 % |
| juillet 1 / 2 / 3 | 21 / 18 / 34 | 5 / 4 / 6 | 12 / 29 / 47 % |
| août 1 / 2 / 3 | 26 / 10 / 16 | 5 / 4 / 4 | 9 / 30 / 41 % |

## Traitement testé

Décade du 11 au 20 juillet 2025, choisie pour sa nébulosité moyenne (29 %) plutôt que pour la meilleure.

1. Recherche STAC, nuages de scène < 80 %.
2. `odc.stac.load` sur une grille fixe EPSG:2154 à 10 m, bords alignés sur des multiples de 10 m (`GeoBox.from_bbox`), `groupby="solar_day"`, rééchantillonnage au plus proche voisin (B11 et SCL à 20 m), `uint16`, `nodata=0`, blocs Dask de 2048 px.
3. Masque : SCL ∈ {4, 5, 6, 7} et réflectances non nulles.
4. Réflectance = (DN − 1000) / 10 000, planchée à 0 ; NDVI et NDMI par date.
5. Médiane sur la décade, nombre d'observations valides par pixel ; pixels hors territoire à nodata.
6. COG DEFLATE, prédicteur 2, blocs de 512, aperçus internes (2 à 32).

## Résultats

| Mesure | Valeur |
|---|---|
| Grille | 14 236 × 9 343 px (133 Mpx), dont 73,6 Mpx dans le territoire |
| Scènes / dates dans le cube | 18 scènes, 4 jours |
| Recherche STAC (exécution 1 / 2) | 8 s / 5 s |
| Chargement + composite (lecture distante, 8 threads) | 262 s / 147 s |
| Écriture des COG | 60 s / 32 s |
| **Total** | **5 min 30 s / 3 min** (variabilité du débit de lecture distante) |
| RAM maximale | 12 Go |
| **Pixels du territoire avec au moins une observation valide** | **99,97 %** |
| Observations valides par pixel : 0 / 1 / 2 / 3 / 4 | 0,03 % / 10,8 % / 68,2 % / 19,5 % / 1,4 % |
| NDVI médian (territoire) | 0,41 |
| NDVI médian **sans** correction de l'offset | 0,28 |
| NDMI médian | −0,00 |

- **L'offset BOA est indispensable** : sans lui, le NDVI médian du territoire est sous-estimé de 0,13 (0,28 au lieu de 0,41). Pour un indice de différence normalisée, un décalage additif sur les deux bandes ne s'annule pas.
- Les valeurs sont plausibles pour la mi-juillet : céréales moissonnées et prairies sèches (NDMI proche de 0), à côté de la végétation dense des haies, forêts et marais.
- **Redondance faible** : 11 % des pixels n'ont qu'une observation valide sur la décade. La médiane n'y filtre plus rien, et un nuage ou une ombre mal classés par SCL passent tels quels. D'où l'intérêt de la bande de qualité, et d'un seuil minimal d'observations pour le calcul des anomalies.

### Taille des fichiers

Première version : un COG par indice, avec l'indice (int16) et le nombre d'observations (int16) en deux bandes, soit **195 Mo par indice et par décade**. Essais sur le NDVI de la décade :

| Variante | Taille |
|---|---|
| 2 bandes int16 (indice + nombre d'observations), DEFLATE | 195 Mo |
| indice seul, int16, DEFLATE, précision 0,0001 | 164 Mo |
| indice seul, int16, ZSTD niveau 9 | 159 Mo |
| indice seul arrondi à 0,001, DEFLATE | 142 Mo |
| nombre d'observations seul, uint8, DEFLATE | 2,7 Mo |

Le nombre d'observations passe donc dans un **COG de qualité séparé, en uint8** (2,7 Mo), commun au NDVI et au NDMI, au lieu d'être dupliqué en int16 dans chaque fichier. ZSTD n'apporte presque rien. Arrondir à 0,001 gagne encore 13 %, mais la précision de 0,0001 est fixée par la spec (§7.3).

Fichiers finaux de la décade (dans `rasters/spike_v0/`, non versionné) :

| Fichier | Type | Taille | Contrôle |
|---|---|---|---|
| `ndvi_2025-07-11_2025-07-20.tif` | int16 × 10 000, nodata −32768 | 164 Mo | valeurs de −1 à 1, médiane 0,41 |
| `ndmi_2025-07-11_2025-07-20.tif` | int16 × 10 000, nodata −32768 | 161 Mo | valeurs de −1 à 1, médiane −0,00 |
| `nb_obs_2025-07-11_2025-07-20.tif` | uint8, 0 = aucune observation ou hors territoire | 2,7 Mo | de 1 à 4 dans le territoire |

Les trois fichiers sont des COG valides : EPSG:2154, 10 m, origine sur des multiples de 10 m, blocs de 512, aperçus 2 à 32. Ils s'ouvrent directement dans QGIS.

### Défaut corrigé pendant le spike

Dans la première version, les pixels hors territoire étaient écrits à −32767 au lieu du nodata −32768 : l'écrêtage était appliqué après le remplissage du nodata. Corrigé (écrêtage, puis remplissage), et le composite a été régénéré. Le futur module d'écriture devra avoir un test qui vérifie le nodata hors emprise.

## Projections

| Poste | Estimation |
|---|---|
| Une décade (NDVI + NDMI + qualité) | 327 Mo, 3 à 6 min |
| Une année (36 décades) | environ 12 Go, 2 à 3 h 30 de calcul |
| Référence 2018–2025, calcul des composites | 288 décades, 15 à 26 h de calcul, en une fois |
| Stockage de la référence | les normales seulement (médiane et dispersion par décade et par indice : 36 × 2 × 2 rasters, environ 25 Go) ; pas les 288 composites (environ 95 Go) |

- La RAM (12 Go) vient de ce que le composite entier est ramené en mémoire avant l'écriture. Pour un département plus grand, ou une machine plus modeste, il faudra écrire bloc par bloc.
- Les jetons SAS de Planetary Computer durent environ une heure et sont posés à la construction du graphe Dask (voir `eo_factory`). Avec 3 à 6 minutes par décade, le risque est nul si chaque décade est un calcul distinct ; le calcul de la référence ne doit pas être lancé comme un seul graphe.

## Conséquences et propositions

| # | Proposition | Nature |
|---|---|---|
| 1 | Planetary Computer comme source Sentinel-2, offset BOA systématique selon `s2:processing_baseline` | Source (fait : spec §4.6) |
| 2 | Un COG int16 par indice et par décade, plus un COG de qualité uint8 (observations valides) commun ; `rst.produit` référence les trois | Organisation des fichiers |
| 3 | Seuil minimal d'observations valides (par exemple 2) pour calculer une anomalie de pixel ; en dessous, pixel non évalué | Méthodologie (V2) |
| 4 | Garder la précision de 0,0001 (spec), ou passer à 0,001 (−13 % de volume) | Méthodologie (V2) |
| 5 | Rééchantillonnage de B11 (20 m) : plus proche voisin testé ; bilinéaire à évaluer en V2 pour le NDMI | Méthodologie (V2) |
| 6 | Écriture bloc par bloc et une décade par graphe Dask (RAM, jetons SAS) | Implémentation (V2) |
| 7 | Prévoir au moins 15 Go par an dans `rasters/`, plus environ 25 Go pour les normales | Exploitation |
