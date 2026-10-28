# Spike V2.0 n°7 — Chiffrage de la brique satellite (végétation et crues des marais)

Date : 2026-10-24 · Département : 85 · Scripts : [`v2_0/`](v2_0/) · Machine : 8 cœurs, 31 Go de RAM · Architecture : [`../architecture_v2.md`](../architecture_v2.md)

## Questions

Avant de coder la V2, chiffrer sur les vraies données : (1) les surfaces par classe de forêt et de culture, (2) le domaine des marais, (3) la détection de l'eau et des crues par Sentinel-1, (4) la stabilité radiométrique de Sentinel-2, (5) médiane ou moyenne, (6) l'apport du NDMI face au NDVI.

Tout est en lecture : rien n'est écrit dans `data/` ni dans la base. Les images sont lues à distance (Planetary Computer), les couches vectorielles à la Géoplateforme de l'IGN. Les sorties intermédiaires restent hors dépôt.

## 1. Classes de forêt et de culture

**BD Forêt V2** : 15 370 polygones, **54 676 ha** dans le territoire, 28 postes (3 postes ne sont pas des forêts : landes, formations herbacées, forêt sans couvert). Aucun champ de millésime dans la couche (la couche porte « 2006-2019 ») : le millésime de la Vendée reste à lire dans la fiche IGN. Regroupement proposé (« purs » : pixels entièrement dans le polygone, après érosion d'un pixel de 10 m) :

| Classe | ha | ha purs | Remarque |
|---|---|---|---|
| Feuillus mélangés et autres | 26 725 | 18 554 | forêt fermée de feuillus hors chênes purs et châtaignier |
| Chênes décidus purs | 5 353 | 4 494 | |
| Pin maritime pur | 5 029 | 4 340 | conifère à feuillage persistant : cible stable |
| Mélange feuillus-conifères | 3 676 | 2 659 | |
| Landes et formations herbacées | 3 321 | 2 419 | |
| Autres conifères | 2 925 | 2 234 | pin laricio, douglas, mélanges de conifères |
| Peupleraie | 2 371 | 1 517 | culture, vallées humides : sensible à l'eau |
| *Réserve* : châtaignier pur | 2 338 | 1 856 | taillis |
| *Réserve* : forêt ouverte | 1 969 | 1 327 | couvert partiel : NDVI mêlé de sol |
| *Exclue* : forêt sans couvert (coupes) | 969 | 724 | |

**RPG 2025** : 143 551 parcelles, **461 136 ha**, taille médiane de 1,4 à 4,5 ha selon la classe ; 64 à 86 % de la surface survit à l'érosion d'un pixel.

| Classe | Parcelles | ha | ha purs |
|---|---|---|---|
| Prairies permanentes | 56 800 | 136 443 | 98 473 |
| Maïs | 16 874 | 82 861 | 67 559 |
| Blé tendre | 13 009 | 70 211 | 57 756 |
| Prairies temporaires | 16 797 | 40 222 | 30 285 |
| Fourrages | 7 631 | 32 361 | 25 932 |
| Autres céréales | 4 993 | 29 416 | 24 510 |
| Tournesol | 3 485 | 19 004 | 15 638 |
| Orge | 3 519 | 15 860 | 12 771 |
| Colza | 1 839 | 10 247 | 8 442 |

Reste, hors classes : protéagineux (7 519 ha), légumineuses à grains, oléagineux divers, gel, légumes, fibres, vignes (environ 23 000 ha en tout). Toutes les classes retenues ont plus de 1 500 ha purs, soit plus de 150 000 pixels : assez pour une statistique stable.

## 2. Domaine des marais

Périmètres Natura 2000 ZPS (Marais poitevin et Marais breton) dans le territoire, moins les marais salants, les zones intertidales, les plages et dunes (CORINE codes 422, 423, 331) et l'estran (BD TOPO) :

| Marais | Brut (ha) | Net (ha) | Retrait (ha) |
|---|---|---|---|
| Poitevin | 41 586 | 41 326 | 260 |
| Breton | 34 378 | 32 657 | 1 721 |
| **Total** | **75 964** | **73 983** | **1 981** |

Le domaine est surtout fait de prairies permanentes (environ 31 000 ha, ce que confirment les masques RPG) ; les cultures annuelles n'y comptent que 7 000 ha. Le réseau maritime (tronçons aval des limites de salure des eaux) **n'est pas encore construit** : voir la section 6.

### 2.1 Marais mouillé, intermédiaire et desséché (Marais poitevin)

L'établissement public du Marais poitevin (EPMP) publie sur [son portail SIG](https://www.epmp-marais-poitevin.fr/data/) une couche **« Grandes entités du Marais poitevin »** (GeoPackage, mise à jour le 22 octobre 2025, EPSG:2154), qui sépare exactement ce qui manquait. Surfaces par entité :

| Entité | EPMP (ha) | Vendée (ha) | Dans le domaine Poitevin net (ha) |
|---|---|---|---|
| **Marais mouillés** | 28 257 | 16 986 | **15 519** |
| Marais intermédiaires | 18 787 | 12 170 | 9 367 |
| **Marais desséchés** | 47 240 | 34 191 | **11 402** |
| Cordons dunaires | 3 809 | 3 000 | 1 347 |
| Fonds de vallée humide | 3 564 | 1 210 | 1 061 |
| Terres hautes | 4 662 | 2 731 | 226 |
| **Slikke (vasières)** | 4 683 | 185 | **127** |
| **Schorre (prés salés)** | 1 138 | 23 | **20** |

- **94 %** du domaine de 41 326 ha est couvert par une entité. La slikke et le schorre sont les zones de marée de la baie de l'Aiguillon : **147 ha** y restent dans le domaine, à exclure. Les cordons dunaires (1 347 ha) ne sont pas des marais.
- La zone du déversoir du Lay (1 941 ha) est classée **marais mouillé** pour 1 561 ha (fonds de vallée humide 134 ha, terres hautes 62 ha).
- La couche **« Unités hydrauliques cohérentes »** découpe le marais en 267 compartiments (types MM, MI, MD) rattachés à leurs gestionnaires (associations syndicales, syndicats de marais) : un découpage plus fin si besoin.
- Les **314 échelles limnimétriques** (niveau d'eau, avec le repère en NGF) et les sondes de l'EPMP donnent les points de mesure du niveau d'eau du marais. Le fichier ne contient que les points, pas les séries : à demander à l'EPMP.
- **Licence : aucune n'est indiquée sur le portail.** Les fichiers ont servi à cette analyse. Avant de les republier ou de les intégrer à `data/`, il faut l'accord de l'EPMP (contact indiqué sur la page : Marion Dulieu, 02 51 56 56 23).
- **Marais breton : aucun équivalent trouvé.** Le SAGE de la baie de Bourgneuf (association porteuse ADBVBB) a un inventaire des zones humides par commune, sans couche téléchargeable repérée ; l'atlas des paysages décrit deux logiques hydrauliques (polders qui évacuent l'eau, marais alimentés en eau par les étiers) sans couche SIG. La Géoplateforme n'a pas de couche de zones inondables pour ce secteur.

### 2.2 Les autres couches du portail de l'EPMP (2026-10-28)

Le portail propose **19 jeux de données** (GeoPackage, aucune licence indiquée, mises à jour de mai 2019 à septembre 2026). J'ai téléchargé et ouvert les 15 qui touchent à l'eau et à la gestion, et chiffré chacun sur le domaine Poitevin net (41 326 ha).

| Couche | Contenu | Dans le domaine | Intérêt pour V2 |
|---|---|---|---|
| **Sondes limnimétriques** | 140 points de mesure du niveau d'eau : producteur (EPMP 61, IIBSN 36, Département 85 13, syndicats), télétransmission (102 oui), fréquence (une mesure par heure pour 58), « point nodal » (24), année de mise en service (renseignée pour 62 ; 36 en 2021, 7 en 2014, 7 en 2017) | 88 sondes | **Fort** : ce sont les mesures qui permettraient de valider les crues. **Les séries ne sont pas dans le fichier** |
| **Échelles limnimétriques** | 314 points (297 de niveau d'eau), cote du repère en NGF, lien avec la sonde (156) et l'unité hydraulique | 187 échelles | Même remarque : points seuls |
| **Règlements d'eau** | 43 unités hydrauliques : règlement d'eau approuvé (33 ; 14 725 ha), expérimentation (3 ; 583 ha), à poursuivre (14 ha) | 15 322 ha | Moyen : les **niveaux d'eau voulus** par saison sont dans les règlements (documents), pas dans le fichier. Ils séparent l'eau d'hiver voulue de l'eau subie |
| **Contrats de marais et protocoles** | 43 zones : contrat avec protocole définitif (14 ; 21 169 ha), expérimentation (5 ; 4 837 ha), engagé (12 ; 3 953 ha) ; année de signature connue pour 19 (2014 à 2023) | environ 31 000 ha | Moyen : un changement de gestion de l'eau (protocole appliqué à partir d'une année) peut **faire varier la crue sans lien avec le climat** ; à garder en note pour lire la tendance |
| **Unités hydrauliques cohérentes (UHC)** | 267 compartiments, type MM / MI / MD, gestionnaires, groupe territorial | 144 unités, 36 937 ha (89 %) | Faible : confirme les grandes entités (voir ci-dessous) |
| **Groupes territoriaux de gestion (GTG)** | Lay, Vendée, Sèvre niortaise, Nord Aunis | Lay 15 153 ha, Vendée 16 205 ha, Sèvre niortaise 6 257 ha, Nord Aunis 0 | Possible découpage géographique des séries, sans lien avec le régime |
| **Associations syndicales** | 36 gestionnaires de marais | 14 couvrent 34 006 ha | Faible |
| **Ouvrages hydrauliques** | 1 854 ouvrages (vantelles, buses, antolles, clapets, 35 stations de pompage) avec fonction, état et gestionnaire | 930 | Faible : aucune série d'ouvertures, explication seulement |
| **Réseau hydraulique** | 72 053 tronçons, hiérarchie : principal 3 212, primaire 2 331, secondaire 8 015, tertiaire 5 529, 52 945 non classés (BD TOPO) | tout le marais | Faible : les canaux font moins de 10 m, sous la taille d'un pixel radar |
| **Unités de gestion de l'OUGC** | 17 unités de gestion de l'irrigation (eau superficielle et nappes) | dont des unités de nappe (Lay 11 642 ha, Vendée 7 757 ha, Autizes 6 661 ha) | **Écarté** : zones hydrogéologiques, exclues par votre décision sur le domaine |
| **Zone humide (1999)** | Périmètre validé le 22 décembre 1999 | 37 336 ha, soit 90 % du domaine | Aucun : cohérent avec la ZPS retenue, mais plus ancien |
| Masses d'eau superficielles, SAGE, périmètres du bassin, PAEC, Natura 2000 | Découpages administratifs | — | Aucun |

- **Les UHC confirment les grandes entités** : sur le domaine, 97 % du marais mouillé des grandes entités (15 064 sur 15 519 ha) tombent dans des UHC de type MM, 95 % du desséché (10 880 sur 11 402 ha) dans des UHC de type MD, mais seulement **67 % de l'intermédiaire** (6 299 sur 9 367 ha) : la frontière du marais intermédiaire est floue. Les grandes entités couvrent 94 % du domaine contre 89 % pour les UHC : **on garde les grandes entités**.
- **Rien d'équivalent n'existe pour le Marais breton** dans ce portail.
- **Les séries de niveaux d'eau sont le manque principal.** Les producteurs (EPMP, IIBSN, Département 85, syndicats) sont multiples. Un avis de marché de l'EPMP (mai 2026, lot 2, référence AOO_2026-02, trouvé par recherche web, non lu en entier) prévoit la refonte de son site de visualisation des niveaux d'eau, ce qui laisse penser que les séries existent mais ne sont pas en téléchargement libre. Rien trouvé par recherche web sur data.gouv.fr ; Hub'Eau et ADES non vérifiés. À demander à l'EPMP, avec la **licence**, dans le même courrier.
- **Intérêt des séries** : les sondes de 2021 (36 de l'IIBSN) ne permettent pas de couvrir la période 2015-2026 ; celles de 2014, 2017 et 2019 (une quinzaine à l'année connue) le feraient en partie. Une validation pixel par pixel n'est pas possible, mais **un test de corrélation entre le niveau d'eau mesuré et la surface de crue du mois** l'est.

## 3. Sentinel-1 : détecter l'eau et les crues

**Lecture** : 33 passages sur les deux fenêtres des marais lus en 68 secondes (environ 2 secondes par passage et par marais), VV seul. Extrapolation à environ 5 800 scènes de 2015 à 2026 : **de l'ordre de 3 heures** de lecture.

### 3.1 Un seuil fixe sur VV ne marche pas

Calibrage sur l'eau permanente connue (grandes surfaces ≥ 1 ha de la BD TOPO, 283 ha en pixels purs), terre sèche (cultures du RPG, 7 094 ha) et prairies permanentes (témoin de crue, 31 074 ha), janvier et août 2024, 2 dates par orbite relative :

| VV (dB) | Eau de référence | Terre sèche | Prairies |
|---|---|---|---|
| p10 / p50 / p90, été | −20,5 / **−15,7** / −10,5 | −13,2 / −9,9 / −7,0 | −16,0 / −13,1 / −10,1 |
| p10 / p50 / p90, hiver | −20,1 / −15,9 / −10,4 | −12,4 / −8,3 / −4,8 | −14,4 / −11,3 / −8,3 |
| Sous −16 dB, été | 47 % | 0,8 % | **9,8 %** |
| Sous −16 dB, hiver | 50 % | 0,2 % | **4,1 %** |
| Sous −18 dB, été | 31 % | 0,1 % | 1,6 % |

- **Même l'eau permanente n'est sombre que pour la moitié de ses pixels** (médiane à −15,7 dB), à cause du vent, de la végétation émergente et des mélanges de pixels.
- **Les prairies sont plus sombres en été qu'en hiver** (herbe rase et sèche) : un seuil unique les prendrait pour de l'eau et masquerait la crue. La décision Q9 « seuil par orbite sur VV » n'est **pas validée**.
- **L'orbite 132 ne voit pas l'eau** (0 % détectée en été, médiane de l'eau à −9,3 dB) : géométrie défavorable. L'orbite 154 est faible (20 %).

### 3.2 Détection par changement

Principe : un pixel est en crue si son VV d'hiver est inférieur de Δ dB à la médiane d'été du même pixel et de la même orbite, **et** inférieur à un seuil absolu ; les pixels déjà sombres en été (eau permanente) sont écartés. Surface détectée (hectares, les deux marais, médiane des passages de janvier-février 2024), avec Δ ≤ −4 dB et VV ≤ −16 dB :

| Orbite | 8 | 30 | 81 | 103 | 132 | 154 |
|---|---|---|---|---|---|---|
| Hiver (ha) | 1 262 | 1 170 | 1 152 | 826 | 0 | 168 |
| Été, le « bruit » (ha) | 396 | 918 | 1 120 | 326 | 0 | 158 |

L'été donne des détections de **plusieurs centaines d'hectares** (sol humide, travaux agricoles, pluie, vent), du même ordre que le signal d'hiver pour certaines orbites : sans autre contrôle, la méthode est bruitée. Les orbites ne concordent pas (168 ha pour la 154, 1 262 ha pour la 8).

### 3.3 Validation par Sentinel-2

Sentinel-2 sert ici de vérité de terrain uniquement : MNDWI = (B03 − B11) / (B03 + B11) > 0 sur des images claires, moins l'eau permanente d'août 2024 (251 ha), dans le Marais poitevin. Deux dates : le 6 janvier 2024 (69 % du domaine valide, environ 3 200 ha de crue) et le 13 janvier (98 %, environ 2 000 ha ; 1 800 sur les pixels communs avec un des passages), comparées aux passages radar à moins de 2 jours (orbites 81, 8 et 30).

| Variante | Précision | Rappel | Écart de surface (3 comparaisons) |
|---|---|---|---|
| **Δ ≤ −3 dB et VV ≤ −16 dB** | 0,55 | 0,51 | **+5 %, −20 %, −4 %** |
| Δ ≤ −4 dB et VV ≤ −16 dB | 0,58 | 0,48 | −8 %, −28 %, −14 % |
| VV ≤ −16 dB seul | 0,49 | 0,55 | +36 %, −10 %, +10 % |
| VV ≤ −18 dB seul | 0,72 | 0,36 | −38 %, −65 %, −29 % |

- **À l'échelle de la surface totale**, la meilleure variante (Δ ≤ −3 dB et VV ≤ −16 dB) donne à 20 % près la surface vue par Sentinel-2 sur 3 comparaisons. **Au pixel**, l'accord est moyen (F1 d'environ 0,55) : les erreurs se compensent à l'échelle du marais.
- Trois comparaisons sont trop peu pour conclure : il faut plus de dates claires, sur plusieurs hivers (2015-2026).

### 3.4 Crue du Lay du 4 février 2025 (image repérée par l'utilisateur)

Image Sentinel-2 d'une seule scène (tuile 30TXS, baseline 05.11), **sans nuage, 100 % de pixels valides**, qui montre le Lay en crue en amont du Marais poitevin, vers La Bretonnière-la-Claye et Lairoux (communes à cheval sur le périmètre Natura 2000 : 45 % de leur surface y est incluse). Fenêtre de 16 × 16 km (25 600 ha), dont 9 138 ha dans le périmètre. Crue vue par Sentinel-2 (MNDWI > 0 hors eau permanente d'août 2024, 75 ha dans la fenêtre) : **1 328 ha dans la fenêtre, 1 283 ha dans le périmètre**. Comparaison avec le passage radar de l'orbite 81, le 3 février, avec la référence d'été 2024 :

| Variante | Fenêtre : écart de surface | Précision | Rappel | Périmètre : écart | Précision | Rappel |
|---|---|---|---|---|---|---|
| **Δ ≤ −4 dB et VV ≤ −16 dB** | **+1 %** (1 339 ha) | 0,70 | 0,71 | **0 %** (1 287 ha) | 0,73 | 0,73 |
| Δ ≤ −3 dB et VV ≤ −16 dB | +12 % | 0,67 | 0,75 | +11 % | 0,70 | 0,78 |
| Δ ≤ −2 dB et VV ≤ −16 dB | +18 % | 0,65 | 0,77 | +17 % | 0,68 | 0,80 |
| VV ≤ −16 dB seul | +27 % | 0,63 | 0,80 | +25 % | 0,66 | 0,82 |
| VV ≤ −18 dB seul | −15 % | 0,77 | 0,66 | −13 % | 0,78 | 0,68 |

- **Sur une crue de rivière nette, l'accord est bien meilleur** qu'en janvier 2024 : F1 de 0,71 à 0,74 au pixel (contre 0,55), et la surface est à 1 % (fenêtre) et 0 % (périmètre) de celle de Sentinel-2 avec Δ ≤ −4 dB. Les crues diffuses de prairies, plus difficiles à voir, restent le point faible.
- La variante retenue (Δ ≤ −3 dB et VV ≤ −16 dB) donne désormais **+5 %, −20 %, −4 % et +11 à +12 %** sur 4 comparaisons : dans les 20 % de Sentinel-2.
- **Limites** : un seul passage (le 3 février, la veille de l'image), la référence d'été de 2024 ; le choix entre Δ ≤ −3 dB et Δ ≤ −4 dB change selon la date (0 % ici, −8 à −28 % en janvier 2024) : il se fixe sur l'ensemble des dates de validation, pas sur celle-ci.

### 3.5 Six autres dates de crue, indiquées par l'utilisateur

Dates : 6 février 2020, 12 décembre 2020, 8 janvier 2021, 11 janvier 2022, 6 janvier 2024, 3 mars 2024 (début de décrue). Chacune est confrontée aux passages radar à moins de 3 jours (orbites 8, 30, 81, 103 et 154 ; la 132 est écartée), avec la référence d'été de l'année précédente (pour décembre 2020, celle de l'été 2020). La zone du **déversoir du Lay** (communes de La Bretonnière-la-Claye, Lairoux, Curzon et La Couture : 1 941 ha dans le périmètre) est séparée du reste du Marais poitevin (39 382 ha). Crue vue par Sentinel-2 (MNDWI > 0 hors eau permanente de l'été précédent), part de la zone valide et hectares :

| Date | Déversoir | Reste du Marais poitevin | Marais breton |
|---|---|---|---|
| 2020-02-06 | 79 % valide, 486 ha | 62 %, 1 174 ha | 95 %, 506 ha |
| 2020-12-12 | 81 %, 289 ha | 59 %, 963 ha | 88 %, 727 ha |
| 2021-01-08 | 87 %, 300 ha | 85 %, 423 ha | 93 %, 604 ha |
| 2022-01-11 | 82 %, 188 ha | 55 %, 320 ha | **6 %** (94 % et 82 % de nuages) : inutilisable |
| 2024-01-06 | 100 %, 923 ha | 67 %, 2 296 ha | 100 %, 933 ha |
| 2024-03-03 | **26 %**, 71 ha | 56 %, 2 644 ha | 99 %, 1 204 ha |

Les comparaisons retenues (zone valide à au moins 50 %, au moins 150 ha de crue vus par Sentinel-2) sont au nombre de 14 pour le déversoir, 12 pour le reste du Marais poitevin et 14 pour le Marais breton. Médianes sur ces comparaisons, sans puis avec le **filtre spatial** du radar (médiane 3 × 3 des valeurs en dB et de la référence, puis suppression des taches de moins de 10 pixels, soit 0,1 ha) :

| Zone | Variante | Accord au pixel (F1) | Précision | Rappel | Écart de surface (médiane) |
|---|---|---|---|---|---|
| **Déversoir** | Δ ≤ −3 dB et VV ≤ −16 dB | 0,76 | 0,83 | 0,74 | −18 % |
| | idem **+ filtre** | **0,81** | **0,92** | 0,77 | −20 % |
| | Δ ≤ −2 dB et VV ≤ −16 dB + filtre | 0,81 | 0,89 | 0,79 | −15 % |
| **Reste du Marais poitevin** | Δ ≤ −3 dB et VV ≤ −16 dB | 0,42 | 0,44 | 0,33 | −21 % (de −55 % à +254 %) |
| | idem + filtre | 0,44 | **0,66** | 0,30 | −47 % |
| | Δ ≤ −2 dB et VV ≤ −16 dB + filtre | 0,46 | 0,61 | 0,34 | −41 % |
| **Marais breton** | Δ ≤ −3 dB et VV ≤ −16 dB | 0,23 | 0,20 | 0,29 | **+53 %** |
| | idem + filtre | 0,31 | **0,40** | 0,25 | −38 % |
| | Δ ≤ −2 dB et VV ≤ −16 dB + filtre | 0,31 | 0,35 | 0,29 | −21 % |

- **L'eau libre du déversoir est détectée très bien** : F1 de 0,81 avec le filtre, précision de 0,92, surface à 15-20 % de celle de Sentinel-2.
- **Le filtre spatial retire le bruit** : la précision passe de 0,44 à 0,66 dans le reste du Marais poitevin, de 0,20 à 0,40 dans le Marais breton, de 0,83 à 0,92 dans le déversoir.
- **Dans le reste du Marais poitevin et dans le Marais breton, l'accord reste faible (F1 de 0,31 à 0,46)**, mais la vérité de terrain de Sentinel-2 y est elle-même en cause (voir 3.6).

### 3.6 Contrôle visuel : la vérité de Sentinel-2 est imparfaite

Pour comprendre les écarts, j'ai affiché, sur les zones où le radar détecte le plus de crue que Sentinel-2 ne confirme pas, l'image en couleurs, le radar en dB, la crue vue par Sentinel-2 et la crue détectée par le radar. Les six vues sont dans `rasters/v2_0/` (`vis_*.png`, `vis2_*.png`, non versionnées). Trois zones de 4 km :

1. **Marais poitevin, 8 janvier 2021** (L93 374,7 / 6 602 km) : une grande prairie inondée sous peu d'eau, sombre, bordée de fossés. Le radar la détecte en bloc (202 ha bruts, 145 ha après filtre). Sentinel-2 ne marque que les fossés (20 ha avec le MNDWI, 28 ha avec un critère de proche infrarouge bas) : **le satellite optique ne voit pas l'eau sous l'herbe**, et le « faux positif » du radar est de la vraie crue.
2. **Marais breton, 8 janvier 2021** (L93 321,4 / 6 664 km) : le MNDWI classe en eau des rectangles blancs (marais salants ou serres), qui sont de **faux positifs de l'optique**. Les détections du radar y sont éparpillées pixel par pixel : du bruit de chatoiement, que le filtre réduit de 127 à 52 ha.
3. **Marais breton, 6 janvier 2024** (L93 322,4 / 6 651 km) : les deux méthodes marquent le même grand bloc de prairies inondées (S2 196 ha, radar 340 ha avec filtre, F1 de 0,64 ; précision de 0,95 contre le critère de proche infrarouge bas), avec du bruit éparpillé dans le bocage au sud.

Ces trois zones ont été choisies là où le radar « sur-détecte » le plus : elles ne sont pas représentatives. Elles montrent surtout que **Sentinel-2 est une vérité de terrain correcte pour l'eau libre et insuffisante pour les prairies inondées**, et qu'il faut une autre référence pour le marais mouillé (voir 6).

**Constat de l'utilisateur (2026-10-28), après examen des six vues** : sur ces exemples, le radar détecte bien de l'eau. Les écarts que je comptais comme « faux positifs » face à Sentinel-2 sont donc en grande partie de la vraie crue (prairies inondées sous peu d'eau). Conséquences : (1) la précision et le F1 face à Sentinel-2 des tableaux 3.5 sont des **bornes basses** hors déversoir du Lay, la vérité optique y étant elle-même incomplète ; (2) l'écart de surface négatif (−47 % dans le reste du Marais poitevin, −38 % dans le Marais breton) mesure surtout ce que Sentinel-2 ne voit pas, pas une sous-détection du radar. Le constat porte sur les trois fenêtres et sur la détection en blocs ; je n'ai pas de confirmation pixel par pixel, et les pixels éparpillés de la fenêtre du Marais breton de 2021 (section 3.6, point 2) restent à trancher.

### 3.7 Bruit d'été avec le filtre spatial

Même mesure qu'en 3.2 (surface détectée, les deux marais, médiane des passages de janvier-février 2024 contre juillet-septembre 2024), avec le filtre spatial (médiane 3 × 3, taches de moins de 10 pixels supprimées). **Le bruit d'été s'effondre (de −90 à −97 %), le signal d'hiver baisse de 30 à 75 % selon l'orbite** (une partie de ce qui est retiré en hiver est aussi du bruit : la précision face à Sentinel-2 monte, voir 3.5) :

| Variante (VV ≤ −16 dB) | | Orbite 8 | 30 | 81 | 103 | 154 |
|---|---|---|---|---|---|---|
| **Δ ≤ −3 dB, sans filtre** | hiver / été (ha) | 1 479 / 776 | 1 515 / 1 664 | 1 614 / 2 104 | 993 / 541 | 258 / 304 |
| **Δ ≤ −3 dB + filtre** | hiver / été (ha) | **1 053 / 62** | **847 / 65** | **811 / 204** | **422 / 17** | **68 / 15** |
| Δ ≤ −4 dB + filtre | hiver / été (ha) | 946 / 11 | 758 / 9 | 655 / 34 | 372 / 5 | 49 / 3 |
| Δ ≤ −2 dB + filtre | hiver / été (ha) | 1 130 / 254 | 891 / 275 | 943 / 758 | 451 / 48 | 89 / 60 |

- **Avec le filtre et Δ ≤ −3 dB, le bruit d'été est de 15 à 204 ha**, contre 304 à 2 104 ha sans filtre. Le rapport entre la surface d'hiver et celle d'été passe de 0,8 à 1,9 (sans filtre) à 4 à 25.
- **Δ ≤ −4 dB** est encore plus silencieux en été (3 à 34 ha), mais il manque davantage de crue en hiver (−27 % au déversoir contre −20 % pour Δ ≤ −3 dB). **Δ ≤ −2 dB** laisse remonter du bruit en été (jusqu'à 758 ha, orbite 81). **Δ ≤ −3 dB avec filtre est le meilleur compromis** de cette mesure.
- **Les orbites ne mesurent pas la même chose** : en hiver, les orbites 8, 30 et 81 donnent 811 à 1 053 ha (à ±13 % de leur moyenne), l'orbite 103 environ la moitié (422 ha) et l'orbite 154 presque rien (68 ha). Seules 8, 30 et 81 sont directement utilisables ; 103 et 154 sous-détectent (angle d'incidence) et ne doivent entrer qu'après un calage par orbite ; 132 ne voit pas l'eau.

## 4. Sentinel-2

### 4.1 Dérive radiométrique (cibles stables, juillet-août 2018-2025)

164 scènes (nuages de scène < 40 %) ; pin maritime pur (83 240 px) et chênes décidus purs. Baselines rencontrées : 02.12, 03.00, 04.00, 05.09, 05.10, 05.11 ; satellites 2A (76 scènes), 2B (75), 2C (13).

| | Pin maritime | Chênes décidus |
|---|---|---|
| NDVI ≤ 2021 (corrigé) → ≥ 2022 | 0,682 → 0,703 (+0,021) | 0,887 → 0,884 (−0,003) |
| **Sans la correction d'offset** | 0,682 → **0,412 (−0,270)** | 0,887 → **0,600 (−0,287)** |
| Écart entre années (médiane annuelle, 2018-2025) | de 0,67 à 0,73 | de 0,87 à 0,91 |
| 2A / 2B / 2C, toutes années | 0,694 / 0,695 / 0,717 | 0,884 / 0,892 / 0,880 |
| 2A / 2B / 2C, 2025 seulement | 0,709 / 0,717 / 0,717 | 0,905 / 0,900 / 0,880 |

- **L'offset BOA est le seul effet massif** : sans lui, le NDVI chute de 0,27 à 0,29 à partir de 2022. Avec lui, le saut au changement de baseline est de +0,02 (pin) et −0,003 (chênes), **au niveau de la variabilité naturelle** (écart d'une année à l'autre jusqu'à 0,06 pour le pin).
- **Pas de différence systématique entre 2A et 2B** (moins de 0,01). Sentinel-2C du pin est à +0,02 (9 scènes, 2025), mais l'année 2025 est aussi plus verte pour 2A et 2B : à surveiller quand les scènes seront plus nombreuses.
- **Limite** : avec 8 ans et cette variabilité, on ne détecte pas un décalage inférieur à environ 0,03. Le contrôle de dérive retenu pour la V2 alerte à partir de ce seuil, qui se précisera avec les 105 mois.

### 4.2 Médiane ou moyenne (juillet 2025, fenêtre de 15 × 15 km, 8 dates)

Observations valides par pixel : médiane de 5 (1 pour 0,1 % des pixels, 3 pour 0,8 %, 4 pour 22,6 %, 5 pour 41,8 %, 6 et plus pour 34,7 %) : **le mois est nettement plus riche que la décade du spike** (1 à 4, 11 % des pixels à une seule observation).

| | Moyenne − médiane |
|---|---|
| NDVI, 5ᵉ / 50ᵉ / 95ᵉ percentile | −0,054 / −0,002 / +0,021 |
| Pixels avec |écart| > 0,02 / 0,05 / 0,1 | 21,4 % / 6,3 % / 1,1 % |
| Pixels avec une observation < médiane − 0,3 (ombre ou nuage probable) | 4,8 % |

| Classe | NDVI médiane | NDVI moyenne | Dispersion des pixels (médiane) | Dispersion (moyenne) |
|---|---|---|---|---|
| Feuillus (BD Forêt) | 0,898 | 0,868 | 0,020 | **0,057** |
| Chênes purs | 0,900 | 0,873 | 0,020 | 0,042 |
| Blé tendre | 0,175 | 0,183 | 0,019 | 0,036 |
| Maïs | 0,701 | 0,682 | 0,182 | 0,150 |
| Prairies permanentes | 0,479 | 0,495 | 0,153 | 0,137 |

**La médiane est retenue** : sur les forêts et les céréales, la moyenne baisse le NDVI de 0,03 (ombres et nuages résiduels sur 5 % des pixels) et **double ou triple la dispersion**. Sur prairies et maïs, les deux diffèrent peu, et l'écart reflète de vraies variations dans le mois (fauches, irrigation).

### 4.3 NDMI contre NDVI (juillet 2022, sec, contre juillet 2023)

5 dates dans la fenêtre pour chacun des deux mois ; classes par année (RPG de l'année pour les cultures, RPG 2025 pour les prairies permanentes, BD Forêt). Écart 2022 − 2023 en unités de dispersion des pixels (σ) :

| Classe | ΔNDVI | Δ/σ NDVI | ΔNDMI | Δ/σ NDMI |
|---|---|---|---|---|
| Prairies permanentes | −0,064 | −0,47 | −0,114 | **−0,97** |
| Maïs | +0,008 | +0,06 | −0,048 | **−0,32** |
| Tournesol | +0,015 | +0,13 | −0,023 | −0,19 |
| Blé tendre (juillet : récolte) | −0,041 | −1,15 | −0,047 | −1,16 |
| Feuillus (BD Forêt) | +0,052 | +1,75 | +0,039 | +0,66 |
| Chênes purs | +0,047 | +1,74 | +0,039 | +0,70 |

- **Le NDMI voit mieux la sécheresse de 2022 que le NDVI sur les prairies** (deux fois plus marqué) **et sur le maïs** (le NDVI ne bouge pas). Sur le blé, les deux se valent (phénologie : la moisson domine). Il apporte une information que le NDVI ne donne pas : il est **retenu**.
- Les forêts sont plus vertes en juillet 2022 qu'en juillet 2023 : la sécheresse de 2022 n'a atteint le houppier qu'en août. Un seul mois ne résume pas une saison.
- **Limite** : une seule fenêtre de 15 km, 5 dates par mois.

## 5. Conséquences pour l'architecture

1. **Q9 est reprise** : pas de seuil fixe sur VV. Méthode retenue pour la suite : **détection par changement** (VV d'hiver inférieur de 3 dB à la médiane d'été du même pixel et de la même orbite, **et** VV ≤ −16 dB ; pixels déjà sombres en été écartés), **filtre spatial** (médiane 3 × 3, taches de moins de 10 pixels supprimées). Mesures : eau libre du déversoir à F1 de 0,81 et précision de 0,92 ; bruit d'été de 15 à 204 ha (section 3.7). Sentinel-2 valide l'eau libre, **pas les prairies inondées** (section 3.6) : il faut une autre vérité de terrain pour le marais mouillé. **Sur les trois fenêtres de contrôle, l'utilisateur confirme que le radar détecte bien de l'eau** (section 3.6) : la méthode est retenue pour les prairies inondées, avec les mesures face à Sentinel-2 lues comme des bornes basses.
2. **Orbites** : exclure la 132 (l'eau n'y est pas visible) ; les orbites 8, 30 et 81 sont cohérentes entre elles (à ±13 %) ; 103 (environ la moitié) et 154 (presque rien) sous-détectent et demandent un calage par orbite.
3. **Valider** (fait pour l'eau libre : 7 dates claires de 2020 à 2025, dont une crue nette du Lay) ; **à faire pour les prairies inondées** : une vérité de terrain (niveaux d'eau des échelles limnimétriques de l'EPMP, repérage de l'utilisateur sur les vues).
3 bis. **Domaine par régime de marais** : le Marais poitevin se découpe en marais mouillé, intermédiaire et desséché avec les « grandes entités » de l'EPMP (section 2.1) ; slikke et schorre (147 ha dans le domaine) sont à exclure. Le Marais breton n'a pas d'équivalent trouvé.
4. **Offset BOA** : confirmé indispensable ; **scènes à baseline inconnue écartées** ; seuil d'alerte de dérive proposé à 0,03 de NDVI.
5. **Médiane** (4.2) et **NDMI en plus du NDVI** (4.3) : confirmés.
6. **Classes** : 7 classes de forêt et 9 de culture (section 1), toutes assez grandes.

## 6. Ce qui reste à faire

- **Réseau maritime** (tronçons hydrographiques aval des limites de salure des eaux et transversales de la mer) et **contrôle de marée** par la hauteur d'eau du SHOM : non faits. La méthode de détection est maintenant fixée (3.7) : ils peuvent être faits. Pour le Marais poitevin, slikke et schorre de l'EPMP donnent déjà l'essentiel (section 2.1).
- **Masque d'eau permanente de Sentinel-1** sur 2015-2025 : non fait ; en 2024, Sentinel-2 en voit 251 ha dans le Marais poitevin.
- **Millésime de la BD Forêt V2** pour la Vendée.
- **Vérité de terrain pour les prairies inondées** (marais mouillé, Marais breton) : l'utilisateur a confirmé l'eau sur les trois fenêtres de `rasters/v2_0/` (2026-10-28). Reste à trancher les pixels éparpillés du Marais breton (2021) et, si l'on veut un chiffre de précision, des niveaux d'eau des échelles limnimétriques de l'EPMP (à demander, séries absentes du fichier).
- **Licence des couches de l'EPMP** : à demander avant tout usage publié.
- **Contour du marais mouillé et desséché pour le Marais breton** : aucun trouvé (ADBVBB, DREAL, syndicats de marais à interroger).
