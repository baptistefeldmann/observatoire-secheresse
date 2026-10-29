# V2 — Architecture de la brique satellite : végétation (Sentinel-2) et eau des marais (Sentinel-1)

*Révisée le 2026-10-24 (deuxième version), puis complétée par les résultats de V2.0 ([spike n°7](spikes/07_v2_chiffrage.md)). **Rien n'est codé dans le pipeline.** Les points ouverts (section 11) deviennent des décisions numérotées dans [`methodologie.md`](methodologie.md) une fois validés, sur des chiffres tirés des vraies données. Références : [`SPEC.md`](SPEC.md) §4.6, §6, §7.3 ; [spike n°4](spikes/04_sentinel2.md) ; décisions D7, D8, D10.*

## 1. Ce que la brique doit faire

Un **indice satellitaire de l'hydrologie, à part de l'indice composite**, fait de **deux indices distincts** (choix de l'utilisateur) :

| Indice | Question | Capteur | Forme du résultat |
|---|---|---|---|
| **Stress de la végétation** | La végétation souffre-t-elle plus que d'habitude pour ce mois ? | Sentinel-2 L2A, **NDVI et NDMI**, au mois | Anomalies de NDVI et de NDMI par classe de forêt et de culture, par zone |
| **Crues des marais** | Quelle surface est en crue ? Quelle tendance depuis 2015 ? Un hiver sans crue annonce-t-il un été sec ? | **Sentinel-1** (radar), VV | **Surface de crue en hectares** (valeur brute, jamais un taux), par mois |

Hors périmètre : pression sur la ressource (V3), prévision (V4), carte d'occupation du sol produite en interne.

## 2. Choix de l'utilisateur

| Sujet | Choix |
|---|---|
| Statut | Deux indices **à part du composite** |
| Végétation | NDVI Sentinel-2 L2A, mensuel (exception à la semaine ISO, à noter en D15), Planetary Computer, `pystac-client` + `xarray` + `odc-stac`, méthode d'`eo_factory` (lue, non copiée) |
| **Radiométrie** | **Identique entre toutes les images** : condition primordiale pour comparer les valeurs de NDVI (section 6.4) |
| Classes de forêt | BD Forêt V2 (prises de vues de 2006), tenue à jour par une carte récente d'arbres (le RPG prime ; pixel gardé s'il est encore un arbre et de NDVI d'été ≥ 0,4, sauf peupleraie ; écart été-hiver pour le feuillage), **sur tout le département** (le suivi NDVI et NDMI ne se limite pas aux marais) ; aucune source récente ne donne mieux pour les essences et les peupleraies ([spike n°7, section 1.2](spikes/07_v2_chiffrage.md)) ; OSO et FORMSpoT possibles avec un compte Dinamis-Theia |
| Classes agricoles | RPG 2025 ; rotation traitée par classe et par année (RPG de chaque année) ; RPG 2025 pour l'année en cours, bruit signalé |
| Regroupement des classes | Sur les surfaces réelles du territoire (V2.0) |
| **Crues** | **Sentinel-1 seulement** ; **période 2015-2026** pour déterminer une tendance ; **seule la surface de crue est publiée, en hectares** (ni la surface en eau totale, ni sa part permanente, ni un pourcentage) ; **domaine des marais indépendant des zones hydrogéologiques** |
| **Domaine des marais** | **Natura 2000 ZPS « Marais poitevin » et « Marais breton… »** (environ 76 000 ha), **sans aucune zone soumise à la marée** : une surface qui varie avec la marée fausserait le calcul (7.2) |
| **NDMI** | Calculé **en plus du NDVI** (bande B11 en plus) ; V2.0 le confirme : sur 2022 (sec) contre 2023, il marque deux fois plus que le NDVI sur les prairies et voit le maïs que le NDVI ne voit pas |
| Anomalie du NDVI | Écart à la médiane de la classe (Q3) |
| Détection de l'eau | **Après V2.0** : pas de seuil fixe sur VV. **Détection par changement** (VV d'hiver inférieur de 3 dB à la médiane d'été du même pixel et de la même orbite, et VV ≤ −16 dB) avec **filtre spatial** (médiane 3 × 3, taches de moins de 10 pixels supprimées) ; validée par Sentinel-2 sur l'eau libre (F1 de 0,81 au déversoir du Lay), pas sur les prairies inondées (Q9, [spike n°7](spikes/07_v2_chiffrage.md)) |
| Contrôle de dérive radiométrique | Cibles stables et seuil proposés sur les données (Q13) |
| Fenêtre de référence | **Élargie** : Sentinel-2 de 2018 à 2026 (référence 2018-2025, 8 ans) ; Sentinel-1 de 2015 à 2026 |

À confirmer : pour Sentinel-2, j'ai compris « fenêtre élargie » comme 2018-2026 (début de l'archive L2A homogène de la spec). L'étape intermédiaire 2022-2026 reste possible puisque la période est un paramètre.

## 3. Contraintes héritées

| Contrainte | Conséquence |
|---|---|
| GeoParquet de `data/` = source de vérité ; `rasters/` ni Git ni DVC | Rasters régénérables ; seuls les agrégats mensuels (petits) sont versionnés par DVC |
| CRS EPSG:2154, grille fixe à 10 m alignée sur des multiples de 10 m | Sentinel-1 est livré en UTM 30N (EPSG:32630) et reprojeté |
| Échelle fixe (D10) : référence figée, jamais glissante | Références figées à 2025 ; 2026 n'y entre jamais |
| Jamais de valeurs brutes agrégées entre variables | Anomalie standardisée avant toute agrégation de NDVI |
| Généricité territoriale | Emprise, zones de marais, classes, périodes : dans `config/` |
| Idempotence ; source en panne ne bloque pas les autres | Un mois déjà écrit n'est pas recalculé ; un échec satellite ne bloque jamais `make hebdo` |
| Tests sans réseau | Réponses STAC enregistrées, cubes de pixels synthétiques |

## 4. Ce que le catalogue offre (Planetary Computer, vérifié le 2026-10-24, sur le territoire + 1 km)

Recherches STAC seulement : rien n'a été téléchargé.

| | Sentinel-1 (`sentinel-1-rtc`) | Sentinel-2 (`sentinel-2-l2a`) |
|---|---|---|
| Couverture | de 2014 à aujourd'hui ; dernière scène du 2026-10-23 | de 2015 ; 2017 : 221 scènes, 2018 : 360, 2019 : 389, 2020 : 372, 2021 : 377 (nuages < 80 %) |
| Homogénéité | **Les mêmes 6 orbites relatives (8, 30, 81, 103, 132, 154) de 2014 à 2026**, mode IW, VV + VH | Satellites 2A et 2B depuis 2017, 2C depuis 2025 |
| Traitement | Gamma0 corrigé du relief, float32 **linéaire**, nodata −32768, 10 m | **Baselines 02.12 (2017-2021), 03.00 (2021), 04.00 (depuis le 2022-01-25), 05.xx** : l'offset de −1000 DN ne s'applique qu'à partir de 04.00 |
| Densité | **Varie** : 2015, 1 satellite (S1A, environ 12 passages par mois) ; 2017-2021, S1A + S1B (environ 23) ; 2022-2024, S1A seul (11 à 16) ; depuis 2025, S1C et S1D (environ 25) | médiane de 42 scènes par mois, 4 à 15 jours d'acquisition ; décembre : 16 à 34 scènes, 4 à 10 jours |
| Produit voisin | — | HLS (S30, Landsat-Sentinel harmonisé, 30 m) existe mais **seulement depuis 2020** |

## 5. Vue d'ensemble

```
 Planetary Computer (STAC)                          Géoplateforme IGN (WFS)
   sentinel-2-l2a        sentinel-1-rtc               BD Forêt V2 · RPG 2018-2025
        │                      │                              │
        ▼                      ▼                              ▼
 sources/sentinel2.py   sources/sentinel1.py          sources/ign_classes.py
 (baseline, plateforme)  (orbite relative, VV)         (mise à la grille, regroupement)
        │                      │                              │
        ▼                      ▼                              │
 raster/composite_ndvi   raster/eau_radar (par passage :      │
 (mensuel : médiane,      dB, filtre, seuil par orbite,       │
  masque SCL, harmonisation  masque d'eau → crue en ha)    │
  radiométrique, QC)            │                              │
        │                       ▼                              │
        │                 médiane mensuelle des surfaces        │
        ▼                       │                              ▼
 indices/vegetation.py   indices/eau.py       ◄────── classes ┘
 (anomalie par classe × zone)   (ha de crue, tendance, anomalie)
        └────────────────┬──────┘
                         ▼
   data/satellite/*.parquet (DVC)  ──►  idx.satellite_mois  ──►  API · dashboard · QGIS
```

## 6. Indice 1 — Stress de la végétation (NDVI, Sentinel-2)

### 6.1 Principe
Pour chaque mois et chaque classe, comparer le NDVI de la classe à celui des mêmes mois de la référence. On ne compare jamais une classe à une autre.

### 6.2 Classes
| Source | Contenu | Accès |
|---|---|---|
| **BD Forêt V2** | 32 postes de formation végétale ; élaborée de 2006 à 2019 ; Licence Ouverte 2.0 | WFS `LANDCOVER.FORESTINVENTORY.V2:formation_vegetale` |
| **RPG** | `code_group`, `code_cultu`, `pp` (prairie permanente) par parcelle | WFS `IGNF_RPG_GRANDES-CATEGORIES-PARCELLES_2025:grandes_categories_parcelles` ; 2018 à 2024 : `RPG.AAAA` |

Regroupement en une dizaine de classes dans `config/nomenclature_ocs.yaml`. Cultures : normales par classe et par année (RPG de chaque année, 2018 à 2021 compris) ; RPG 2025 pour 2026, bruit signalé. Forêts (BD Forêt V2 ancienne : une coupe ou une tempête depuis 2019 laisse un pixel classé « forêt ») et prairies permanentes : classes de confiance.

### 6.3 Composite mensuel : médiane
Sur un mois, un pixel a 3 à 8 observations valides ; la médiane ignore voiles, ombres et brumes que le masque de nuages laisse passer, ce que la moyenne ne fait pas. Bandes : **B04, B08, B11 et SCL**. B04 et B08 sont à 10 m ; B11 est à 20 m et ramenée à 10 m (plus proche voisin au spike ; le bilinéaire est à évaluer). La réflectance de B11 reçoit le même offset par baseline.

### 6.4 Même radiométrie pour toutes les images (condition primordiale)

Un NDVI n'est comparable d'un mois ou d'une année à l'autre que si les réflectances le sont. Les sources de discordance connues, et la parade pour chacune :

| Risque | Parade |
|---|---|
| **Décalage BOA** : depuis la baseline 04.00 (2022-01-25), les DN portent +1000 ; sans correction, le NDVI médian du territoire est faux de 0,13 (spike) | Offset lu **par scène** selon sa baseline ; **scène à baseline inconnue écartée et comptée au rapport** (plus strict qu'`eo_factory`, qui la déduit de la date) |
| **Plusieurs baselines** dans la période (02.12, 03.00, 04.00, 05.xx), avec d'éventuels autres changements de traitement que l'offset | **Contrôle de dérive** : NDVI médian mensuel de **cibles stables** (forêts de conifères et chênes verts de la BD Forêt, sol nu) ; comparaison aux mêmes mois avant et après chaque changement de baseline ; alerte au-delà d'un seuil fixé sur les données |
| **Plusieurs satellites** (2A, 2B, 2C) | Même contrôle, scindé par plateforme : NDVI des cibles stables d'un même jour, 2A contre 2B contre 2C |
| Mélange de niveaux ou de bandes | **L2A uniquement**, jamais de L1C ; mêmes bandes B04 et B08 natives à 10 m |
| Réflectances aberrantes (saturation, négatives) | Réflectance = (DN − offset) / 10 000, négatifs ramenés à 0, NDVI par date **avant** la médiane |
| Lectures corrompues (jetons expirés) | Contrôle d'intégrité (section 9.1) |

Pour une radiométrie encore plus homogène, HLS (Landsat-Sentinel harmonisé, avec ajustement des bandes) existe sur Planetary Computer mais à 30 m et seulement depuis 2020 : il ne couvre pas 2018-2019 et dégraderait les petites parcelles du bocage. Il peut servir de **contrôle croisé** pour 2020 et après, pas de source de base.

### 6.5 Anomalie
Anomalie du pixel = NDVI du mois − médiane de la classe pour ce mois sur la référence ; médiane par zone × classe ; valeur standardisée par le rang parmi les années de la référence (D10). Avec 2018-2025, la référence compte 8 ans : la classe 1 est atteinte (-1,54 au plus bas, contre un seuil de -1,28), le niveau d'incertitude reste celui d'une référence courte (D7 exige 15 ans), signalé « hors référence ».

## 7. Indice 2 — Crues des marais (Sentinel-1)

### 7.1 Principe et résultat
Une surface d'eau calme réfléchit le signal radar loin du capteur : elle est sombre (rétrodiffusion basse en VV), **par tous les temps**. Pour chaque passage, on classe les pixels du domaine des marais en eau ou non, on retire l'eau permanente (canaux, fossés, étiers), on somme la surface restante, puis on prend la **médiane des surfaces des passages du mois**.

**Seul résultat publié : la surface de crue, en hectares** (1 pixel = 0,01 ha), par mois et par marais. C'est une valeur brute, **jamais un taux** : pas de pourcentage d'une zone.

| Élément | Définition |
|---|---|
| **Surface de crue (ha)** | Médiane mensuelle, sur les passages du mois, de la surface en eau hors eau permanente |
| Eau permanente (interne, non publiée) | Masque fixe : pixels en eau dans plus de la moitié des passages de juillet à septembre sur 2015-2025 ; ne sert qu'à la soustraction |
| **Tendance** | Surface de crue d'hiver (décembre à mars) de 2015 à 2026 : pente de Theil-Sen, test de Kendall (même démarche que D12) |
| Anomalie | Écart à la médiane du même mois sur 2015-2025 ; rang parmi 11 ans |

Le masque d'eau permanente est fixe, pour que la série soit comparable dans le temps ; un contrôle de sensibilité le calcule année par année.

### 7.2 Domaine : où mesure-t-on les crues ?
**Les zones hydrogéologiques du projet (`MARAIS_BRETON`, `MARAIS_POITEVIN`) sont écartées** : ce sont des unions de masses d'eau souterraine (128 058 ha), qui englobent bocage, villages et littoral. Les crues se mesurent dans les **marais eux-mêmes**, d'après un périmètre officiel externe. Candidats, sur le territoire (chiffres du 2026-10-24, WFS de la Géoplateforme) :

| Source | Contenu | Surface dans le territoire | Remarque |
|---|---|---|---|
| **Natura 2000 ZPS** (et Ramsar : mêmes périmètres) | « Marais poitevin » 41 586 ha ; « Marais breton, baie de Bourgneuf, île de Noirmoutier et forêt de Monts » 34 378 ha | **environ 76 000 ha** | Périmètres des deux grands marais ; contiennent aussi dunes, forêt de Monts, île de Noirmoutier, estran de la baie de Bourgneuf |
| ZPS « Dunes, forêt et marais d'Olonne » et SIC de Talmont, du Jaunay, d'Yeu | petits marais du littoral | 2 835 + 1 824 + 806 ha | À ajouter si l'on veut les petits marais |
| CORINE Land Cover 2018, marais (411, 421) | marais intérieurs et maritimes | 3 798 + 1 836 ha | Trop partiel : le marais desséché, classé en prairie, est absent |
| IGN, zones humides BCAE | 3 909 polygones | 12 869 ha | Trop fragmenté et partiel |
| Zones hydrogéologiques du projet | — | 128 058 ha | **Écartées** |

Le périmètre est lu dans `config/projet.yaml` (un bloc `marais`), pas codé en dur. Il donne une **surface brute en hectares**, sans notion de taux. Retenu : les deux grands marais ; les petits marais du littoral ne sont pas retenus (dunes et marais d'Olonne, Talmont, Jaunay, île d'Yeu : proches de la mer, donc les plus exposés à la marée).

**Régimes du marais (Marais poitevin).** L'établissement public du Marais poitevin (EPMP) publie une couche **« Grandes entités »** qui sépare le **marais mouillé**, le **marais intermédiaire**, le **marais desséché** et, pour la marée, la **slikke** et le **schorre** ([spike n°7, section 2.1](spikes/07_v2_chiffrage.md)). Dans le domaine Poitevin net (41 326 ha, 94 % classés) : mouillé 15 519 ha, intermédiaire 9 367 ha, desséché 11 402 ha, cordons dunaires 1 347 ha, fonds de vallée humide 1 061 ha, terres hautes 226 ha, **slikke 127 ha et schorre 20 ha (zones de marée, à exclure)**. Le marais desséché est drainé pour l'agriculture : les crues y sont évitées, et ce qu'on y voit n'a pas le sens d'une crue naturelle. Le **déversoir du Lay** (La Bretonnière-la-Claye, Lairoux, Curzon, La Couture ; 1 941 ha) est classé marais mouillé pour 1 561 ha. **Licence non indiquée par l'EPMP : à demander avant usage publié.** Pour le **Marais breton, aucune couche équivalente n'a été trouvée.**

**Exclusion de la marée.** Une surface en eau qui monte et descend avec la marée, à l'heure du passage du satellite, n'est pas une crue : elle fausserait le calcul. Les **marais salants sont exclus** (eau de mer gérée). Pour le reste, le domaine final est le périmètre Natura 2000 **moins toute zone soumise à la marée**, par trois couches complémentaires.

**Couche 1 — limites officielles (BD TOPO `limite_terre_mer`).** La couche ne contient pas que le trait de côte. Sur votre territoire (WFS, 2026-10-24) :

| Contenu | Lignes | Ce qu'elle délimite |
|---|---|---|
| Trait de côte, niveau « plus hautes eaux » | 1 325 | La limite entre terre et mer |
| Niveau « plus basses eaux » | 266 | Le bas de l'estran |
| **Limite de salure des eaux** | **27 (14 dans le domaine)** | Jusqu'où l'eau salée remonte dans une rivière |
| **Limite transversale de la mer** | **22 (13 dans le domaine)** | Où un cours d'eau cesse d'être maritime |
| Limite des affaires maritimes | 23 (9 dans le domaine) | Limite administrative de la mer |

Le **trait de côte à lui seul ne suffit pas** : il sépare la terre de la mer, mais la marée remonte plus loin, dans les estuaires et les étiers. Ce sont les limites de salure des eaux et les limites transversales de la mer, présentes à une quinzaine d'endroits dans le domaine, qui marquent la fin de l'influence de la mer sur chaque cours d'eau.

Méthode prévue : suivre le réseau hydrographique de la BD TOPO **depuis la mer vers l'amont jusqu'à la première limite** de salure des eaux ou transversale de la mer ; ces tronçons forment le **réseau maritime** ; on le borde d'une marge et on retire cette emprise du domaine. S'y ajoutent l'estran de la BD TOPO, les zones intertidales, les plages et dunes (CORINE codes 423 et 331) et les marais salants (code 422). **Mesuré en V2.0 ([spike n°7, section 2.3](spikes/07_v2_chiffrage.md))** : le parcours depuis la mer « fuit » dans le réseau maillé des marais (80 % des tronçons atteints) ; la méthode retenue limite le parcours aux tronçons **marqués salés ou d'estuaire, non fictifs** (variante D, 113 km dans le domaine : 25 km dans le Marais poitevin, 88 km dans le Marais breton). Elle s'arrête d'elle-même au **barrage du Lay** (46,347 ; −1,336), comme l'indique l'utilisateur ; la variante C, qui ajoutait les canaux larges non salés, laissait fuir le parcours dans le maillage des canaux (8 km dans le Marais poitevin) et a été abandonnée le 2026-10-29. Les marais salants, l'estran, les zones intertidales, les plages et dunes sont déjà retirés du domaine net (0 ha de plus).

**Couche 2 — par les données.** *Remplace l'intermittence d'été prévue (non testée), qui se heurte à la dérive de VV entre été et hiver.* **Corrélation par pixel (30 m) entre le radar VV des étés 2022-2025 et la hauteur de marée à l'heure du passage** (SHOM, La Pallice pour le Marais poitevin, Les Sables-d'Olonne pour le Marais breton) : sont retirés les pixels avec r < −0,5 sur l'une des deux orbites utilisées, élargis de 30 m. Ils représentent 0,1 % du Marais poitevin (38 à 43 ha) et 0,22 % du Marais breton (72 à 74 ha), 50 à 200 fois plus que le hasard, tous à moins de 250 m du réseau maritime sauf quelques ha d'étiers que le réseau ne contient pas. Le masque est calculé une fois sur 2022-2025 et **figé** (comme la référence, D10).

**Couche 3 — contrôle.** **Corrélation entre la surface détectée de chaque passage et la hauteur de marée à l'heure du passage** : elle doit être nulle. **Mesurée en V2.0 sur les étés 2022-2025 : r de +0,00 à +0,06 (p ≥ 0,64), nulle dès le domaine de départ comme dans le domaine final** ([section 2.3](spikes/07_v2_chiffrage.md)). À refaire avec les crues d'hiver dès que la série sera calculée, puis à chaque mise à jour de la méthode.

**Ce que retirent les couches de surface (chiffres du 2026-10-24).** Le domaine Natura 2000 compte 75 964 ha dans le territoire (Marais poitevin 41 586 ha, Marais breton 34 378 ha). Il s'arrête déjà aux limites des communes, donc l'estran de la BD TOPO n'y représente que **298 ha**. Les marais salants de CORINE en font **1 467 ha** (remplis d'eau de mer par la marée et gérés : leur eau n'est pas une crue), les zones intertidales 56 ha, les plages et dunes 127 ha. **Environ 1 950 ha au plus (2,6 %) sont donc retirés par ces couches de surface**, auxquels s'ajoutent le réseau maritime et sa marge.

En revanche, la marée remonte dans les **étiers et les estuaires**, que ces couches ne décrivent pas : le domaine compte **9 436 ha à moins de 500 m de la limite terre-mer, 15 541 ha à moins de 1 km et 24 629 ha à moins de 2 km**. Ce sont le réseau maritime (couche 1) et les couches 2 et 3 qui traitent cette zone. Un **contrôle de sensibilité** compare la série avec et sans la bande de 2 km de la côte : si la tendance ne change pas, le résultat ne dépend pas de la marée.

**Domaine final (mesuré en V2.0, marge de 250 m validée le 2026-10-29)** : domaine net **moins** le réseau maritime (variante D) avec **250 m de marge** **moins** le masque des pixels corrélés. **Marais poitevin 41 322 → 40 647 ha (−1,6 %), Marais breton 32 653 → 31 656 ha (−3,1 %)**. Dans le domaine final : aucun pixel corrélé à la marée, corrélation par passage de +0,00 à +0,05. Une bande côtière (500 m ou 2 km) supprimerait la marée aussi bien mais retirerait 5 000 à 15 200 ha de plus dans le Marais breton pour 22 à 23 ha de marée en moins : non retenue. Le contrôle de sensibilité prévu (série avec et sans bande de 2 km) reste à faire quand la série existera.

**Domaine de la surface de crue : sans la forêt (décision du 2026-10-29).** Le périmètre Natura 2000 contient la forêt dunaire de Longeville, la pointe d'Arçay et des boisements du marais (BD Forêt : 3 441 ha dans le domaine final du Marais poitevin, 2 386 ha dans celui du Marais breton), où le radar ne voit presque pas d'eau (0,08 % et 0,29 % des pixels en hiver, contre 2,1 % et 1,3 % pour les prairies). **La forêt reste dans le suivi NDVI et NDMI, mais est retirée du domaine de la crue, avec les « cordons dunaires » de l'EPMP (100 ha de plus hors forêt dans le Marais poitevin) : Marais poitevin 37 107 ha, Marais breton 29 270 ha.**

Les marais endigués (Marais breton, Marais poitevin desséché) sont parfois plus bas que la mer mais protégés par des digues et des portes : l'altitude seule ne permet pas de les distinguer, d'où le recours aux données.

### 7.3 Homogénéité pour une tendance de 2015 à 2026
- **Géométrie constante** : les 6 mêmes orbites relatives sur toute la période. Le seuil d'eau est calé **par orbite relative** (angle d'incidence).
- **Densité variable** : de 11 à 26 passages par mois selon les années (2015 un seul satellite, 2017-2021 deux, 2022-2024 un, puis plusieurs). Un maximum mensuel serait biaisé par la densité ; la **médiane des passages** ne l'est pas. Contrôle de sensibilité : refaire la série avec Sentinel-1A seul, présent toute la période.
- **Limites physiques** : le vent agite l'eau et peut la faire passer pour du sol ; la végétation émergente (roseaux, haies) brouille le signal ; un marais couvert de végétation haute peut sous-estimer la crue. Calibrage : histogramme du VV sur les marais en hiver (crue) et en été (sec), par orbite relative.

## 8. Périodes

| Série | Période | Référence figée (D10) | Conséquence |
|---|---|---|---|
| NDVI | 2018 à 2026 | 2018-2025 (8 ans) | Classes 1 à 7 accessibles ; « hors référence » (moins de 15 ans) |
| Crues | 2015 à 2026 | 2015-2025 (11 ans) pour l'anomalie ; la tendance utilise tout | La valeur publiée est l'hectare ; le rang sert à situer l'année |

La période de chaque série est un paramètre de `config/projet.yaml`. Une étape intermédiaire 2022-2026 reste possible (référence de 4 ans : pas de classe 1, car -1,23 est au-dessus du seuil de -1,28).

## 9. Pipelines

### 9.1 Sentinel-2 mensuel (NDVI), d'après `eo_factory`
1. **Recherche STAC** (`pystac-client`) sur l'emprise (+ 1 km), nuages de scène < 80 % côté serveur puis client, reprises réseau (408, 429, 5xx), pagination comprise.
2. **Cube paresseux** (`odc-stac`, Dask) sur la grille 10 m EPSG:2154 : `groupby="solar_day"`, `dtype` et `nodata` explicites, SCL en plus proche voisin.
3. **Masque** : liste blanche SCL {4, 5, 6, 7} ; la classe 0 et toute valeur hors 0-11 sont non valides.
4. **Harmonisation** (6.4) : offset par scène selon la baseline, scènes à baseline inconnue écartées.
5. NDVI par date, **médiane** du mois, nombre d'observations valides.
6. **Contrôles** : fraction de pixels jamais valides ; redondance moyenne ; **intégrité** (le nodata écrit doit coïncider avec celui de SCL, sinon lectures corrompues : relance en re-signant les URL) ; contrôle de dérive sur les cibles stables.
7. Écriture COG bloc par bloc, nodata exact hors emprise, enregistrement dans `rst.produit` (scènes, baseline, plateforme).

### 9.2 Sentinel-1 par passage, agrégé au mois
1. Recherche STAC `sentinel-1-rtc` sur les fenêtres des marais.
2. Lecture fenêtrée de **VV seul** (VH n'est pas nécessaire à l'eau), reprojection sur la grille, conversion en dB (10·log10), nodata −32768 exclu.
3. Filtrage du chatoiement : médiane 3 × 3 sur le VV en dB et sur la référence d'été.
4. **Détection par changement** : VV inférieur de 3 dB à la médiane d'été du même pixel et de la même orbite relative (référence : juillet à septembre de l'année précédente) **et** VV ≤ −16 dB ; pixels déjà sombres en été (référence < −16 dB) écartés ; taches de moins de 10 pixels supprimées ; domaine des marais (zones de marée exclues). Orbites 8, 30 et 81 directement utilisables ; 103 et 154 après calage ; 132 écartée.
5. Retrait de l'eau permanente, **surface de crue du passage (ha)** (les scènes d'un même passage sont fusionnées), conservée dans un tableau passage × marais.
6. Médiane mensuelle ; tendance et anomalie.
7. Contrôle d'intégrité (fraction de nodata de la fenêtre comparée à l'emprise du passage).

Un mois = un graphe de calcul distinct (jetons d'une heure). Une reprise saute ce qui est déjà écrit.

## 10. Données, restitution, exploitation

| Contenu | Emplacement | Versionnement | Volume |
|---|---|---|---|
| Composites NDVI et NDMI mensuels, qualité | `rasters/mensuel/AAAA-MM/` | aucun | 330 Mo par mois ; 105 mois (2018-2026), environ 35 Go |
| Surface de crue par passage et par marais | `data/satellite/crue_passages.parquet` | **DVC** | quelques Mo (environ 5 800 scènes) |
| Masques d'eau et de crue par passage (périmètres des marais) | `rasters/eau/` | aucun | quelques Mo par passage |
| Classes mises à la grille | `rasters/classes/` | aucun | à mesurer |
| Normales et agrégats mensuels | `data/satellite/` | **DVC** | quelques Mo |

Table proposée (migration 0006, à valider) :
```
idx.satellite_mois (emprise,          -- NDVI : zone_id d'une zone du projet ; crue : identifiant du marais (config), une ligne « total » par marais et, pour le Marais poitevin, une ligne par régime (mouillé, intermédiaire, desséché ; Q14)
                    mois, indice ('ndvi' | 'ndmi' | 'crue'),
                    classe_ocs,       -- NDVI : classe de forêt ou de culture ; crue : NULL
                    valeur_brute,     -- NDVI et NDMI : anomalie ; crue : surface de crue en ha
                    rang, n_annees_ref, valeur, classe,   -- valeur et classe : NDVI et NDMI seulement
                    n_pixels, pct_valides, hors_reference, detail jsonb, version_methodo)

- **Calcul (estimations extrapolées du spike, à mesurer)** : Sentinel-2, 7 à 13 minutes par mois en 2022-2026 et 5 à 9 en 2018-2021, soit **environ 11 à 20 heures** pour 105 mois, reprenable, hors `make hebdo`. Sentinel-1 : environ 5 800 scènes, lecture fenêtrée de VV seul : de l'ordre de quelques heures.
- **Restitution** : tuiles par un service distinct de l'API (garde l'image de 228 Mo), QGIS par couche XYZ, onglet « Satellite » du dashboard (séries mensuelles, tendance des crues en hectares) ; pas de rasters sur le site public, seulement les séries.
- **Tests** : réponses STAC enregistrées ; offset BOA par baseline (une scène de chaque baseline) ; scène à baseline inconnue écartée ; conversion en dB ; nodata hors emprise ; contrôle d'intégrité (un cube corrompu est refusé) ; détection d'un saut de dérive sur une série synthétique ; surface en hectares sur un masque fait à la main ; idempotence ; `tests/test_api_legere.py` reste en place.

## 11. Points ouverts

**Décidés** : Q3 (NDVI : écart à la médiane de la classe, puis rang) ; Q4 (domaine : Natura 2000 ZPS des deux grands marais, sans zone soumise à la marée, marais salants exclus ; **la forêt (BD Forêt) est retirée du domaine de la crue, mais reste dans le NDVI et le NDMI, 2026-10-29**) ; Q6 (NDMI calculé en plus du NDVI) ; Q9 (eau : détection par changement avec filtre spatial, voir 9.2) ; Q12 (seule la surface de crue est publiée, en hectares) ; Q13 (cibles stables et seuil de dérive proposés sur les données en V2.0) ; **Q14 (2026-10-28) : la crue est calculée et stockée par régime, publiée avec le total en tête et le détail dessous ; le déversoir du Lay n'a pas de ligne à part, il est compté dans le marais mouillé** (chaque pixel garde la classe des grandes entités de l'EPMP : 1 561 des 1 941 ha du déversoir sont du marais mouillé) ; **Q15 (2026-10-28) : le Marais breton reste en un seul bloc** tant qu'aucun découpage n'est obtenu. **Q19 (2026-10-29) : exclusion de la marée validée** : réseau maritime en variante D (salé ou estuaire, arrêt au barrage du Lay), marge de 250 m, masque des pixels corrélés à la marée (r < −0,5, élargi de 30 m, figé sur 2022-2025) ; 675 ha retirés dans le Marais poitevin et 997 ha dans le Marais breton. **La forêt (BD Forêt) est retirée du domaine de la crue** (37 107 ha et 29 270 ha), gardée dans le NDVI et le NDMI.

**Résultats de V2.0** ([spike n°7](spikes/07_v2_chiffrage.md)) : 7 classes de forêt et 9 de culture chiffrées ; médiane et NDMI confirmés ; offset BOA indispensable, aucune dérive détectable au-delà de 0,03 de NDVI ; **seuil fixe sur VV invalidé** ; **détection par changement avec filtre** : eau libre du déversoir du Lay à F1 de 0,81 et précision de 0,92, bruit d'été de 15 à 204 ha, orbites 8, 30 et 81 cohérentes à ±13 %, 132 inutilisable ; **Sentinel-2 ne voit pas l'eau sous l'herbe**, donc pas de vérité optique pour les prairies inondées ; **l'utilisateur confirme sur les trois vues de contrôle que le radar y détecte bien de l'eau** (les mesures face à Sentinel-2 sont des bornes basses).

**Restent ouverts**

| # | Question | Proposition |
|---|---|---|
| Q16 | **Vérité de terrain des prairies inondées** | **Partiellement levée (2026-10-28)** : l'utilisateur confirme l'eau détectée sur les trois vues de `rasters/v2_0/`. Reste, pour chiffrer une précision : niveaux d'eau des échelles limnimétriques de l'EPMP (à demander) |
| Q17 | **Licence des couches de l'EPMP** | À demander à l'EPMP |
| Q18 | **Orbites 103 et 154** : calage par orbite ou exclusion ? | Exclure tant qu'un calage n'est pas établi sur plus de dates |

Restent aussi à faire : contrôle de marée avec les crues d'hiver et sensibilité à la bande côtière (une fois la série calculée).

## 12. Étapes proposées

| # | Étape | Sortie |
|---|---|---|
| V2.0 | Surfaces par classe de la BD Forêt V2 et du RPG 2025 (millésime de la BD Forêt pour la Vendée : **fait, prises de vues de 2006, diffusée en 2009**, voir [spike n°7, section 1.1](spikes/07_v2_chiffrage.md)) ; histogramme du VV sur les périmètres de marais en hiver et en été, par orbite relative ; masque d'eau permanente ; **masque de marée** (réseau maritime de la BD TOPO avec marge, pixels corrélés à la hauteur de marée du SHOM : fait, Q19 décidée le 2026-10-29) ; **contrôle de dérive radiométrique sur quelques mois de baselines différentes** (cibles stables) ; essai médiane contre moyenne sur un mois ; **NDMI contre NDVI sur un mois de 2022 (sécheresse) et un de 2023** | Regroupement des classes, seuil d'eau (Q9), cibles stables (Q13), domaine (Q4) |
| V2.1 | Classes mises à la grille ; `config/nomenclature_ocs.yaml` ; périodes et domaine des marais dans `config/projet.yaml` | Décision D15 : classes, mensuel, périodes |
| V2.2 | **Crues Sentinel-1 2015-2026** (calcul léger, déjà exploitable : tendance en hectares) puis composites NDVI mensuels | Séries de crue ; COG, `rst.produit` |
| V2.3 | Agrégats zone × classe, référence, rang ; test de l'hypothèse « hiver sans crue, été sec » avec les nappes et les arrêtés | `idx.satellite_mois`, décision D16 |
| V2.4 | API, tuiles, dashboard, QGIS | Onglet « Satellite » |
