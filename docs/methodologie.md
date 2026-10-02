# Méthodologie — décisions

Ce document consigne les choix de méthode qui précisent ou modifient la spécification (§6 de [`SPEC.md`](SPEC.md)). Chaque décision porte un identifiant cité dans le code et la configuration. Une décision ne change qu'avec une nouvelle entrée datée ; le champ `version_methodo` des tables d'indices relie chaque résultat à l'état de ce document.

## D1 — Fraîcheur des données piézométriques

*2026-09-30 · issu du [spike n°2](spikes/02-03_hubeau_historique.md)*

**Constat.** Aucune station de Vendée n'est diffusée en temps réel. Les chroniques sont journalières mais publiées par lots : selon la station, la dernière mesure date de 11 jours à 7 mois.

**Décision.** L'IPS d'une station est calculé sur le dernier mois disponible, et la date de sa dernière mesure est conservée avec l'indice. Une station n'entre dans le composite de la semaine que si cette mesure a moins de `indices.ips.fraicheur_max_jours` jours (`config/projet.yaml`, 45 jours). Au-delà, elle reste affichée avec son ancienneté, et les poids de la zone sont renormalisés comme prévu au §6.4.

**Conséquence attendue.** Dans le marais breton, où presque toutes les stations sont mises à jour deux fois par an, l'IPS sera souvent absent du composite.

## D2 — IPS dans le bocage

*2026-09-30 · issu du spike n°3*

**Constat.** Le socle compte 5 piézomètres ayant au moins 15 ans sur la référence, dont 2 à 3 à jour. La spec le disait quasiment non couvert et donnait à l'IPS un poids nul.

**Décision.** Poids de 0,15 pour l'IPS dans le bocage. Les nappes de socle, peu profondes, réagissent vite et sont en partie redondantes avec les débits, d'où un poids faible.

## D3 — ONDE hors du composite en V1

*2026-09-30 · issu du spike n°2*

**Constat.** ONDE n'existe que depuis 2012 (moins de 15 saisons). Chaque zone compte environ 7 stations, donc la part d'assecs avance par paliers d'environ 14 %. Au printemps, cette part est nulle presque tous les ans. Une standardisation statistique n'est pas fiable. Des seuils fixes marqueraient le bocage comme « sec » tous les étés, car ses petits cours d'eau s'y assèchent normalement.

**Décision.** En V1, ONDE est une couche affichée à part (carte et dashboard), par zone et par campagne, mais n'entre pas dans l'indice composite. Son poids initial (§6.4) est redistribué au prorata sur les autres composantes, puis arrondi (`config/zones.yaml`). Hors campagne, la couche est « hors période de suivi », jamais zéro.

**À réexaminer** quand l'historique permettra une standardisation par rapport aux saisons passées.

Pondérations qui en résultent (avec D2) :

| Zone | SPI 3 mois | IPS | Débits |
|---|---|---|---|
| Sud-Vendée sédimentaire | 0,25 | 0,50 | 0,25 |
| Marais breton, marais poitevin | 0,30 | 0,40 | 0,30 |
| Bocage | 0,40 | 0,15 | 0,45 |

## D4 — Raccordement de stations hydrométriques

*2026-09-30 · issu du spike n°2*

**Constat.** Sur un même site, une station ancienne peut être remplacée par une nouvelle, ce qui coupe la série en deux.

**Décision.** Les séries des stations d'un même site sont fusionnées quand elles concordent sur leur période commune. La liste est explicite, dans `config/stations.yaml` : pas de raccordement automatique. Pour chaque date, on retient la valeur de la première station de la liste qui en a une. L'indice est rattaché au site raccordé.

| Site | Stations (par priorité) | Vérification | Retenu |
|---|---|---|---|
| Sèvre nantaise à Tiffauges | `M711241020` > `M711241010` | 5 128 jours communs, corrélation 0,994, rapport médian 0,99 | oui |
| Boulogne | `M811261020`, `M811261010` | aucun recouvrement, stations sur deux communes | non |
| Yon à Nesmy / Chaillé | `N342301021`, `N342301020` | 5 jours communs seulement | non, à revoir (rapport des surfaces de bassin) |

## D5 — Découpage du territoire en zones

*2026-09-30*

**Constat.** Les zones de la spec n'avaient ni contour ni règle de construction. Or il faut un contour pour rattacher les stations à une zone, agréger les mailles météo et cartographier les résultats. Deux référentiels étaient candidats : les masses d'eau souterraine, qui suivent une logique hydrogéologique, et les zones d'alerte sécheresse, qui suivent une logique administrative et contiennent souvent trop peu de stations.

**Décision.** La géométrie d'une zone est l'**union de masses d'eau souterraine affleurantes** (SANDRE, EDL 2019, horizon 1). Elle peut être **croisée avec l'union de zones d'alerte** (SANDRE `ZAS`, statut « Validé », code `CdZAS`). La construction est décrite dans `config/zones.yaml` et appliquée par `pipeline/zonage.py`.

- Les zones sont rendues disjointes dans l'ordre du fichier. Un chevauchement de plus de `fragment_max_km2` (20 km²) est une erreur.
- Les fragments et les lacunes de moins de 20 km², dus aux limites qui ne coïncident pas entre référentiels et aux contours du littoral, sont rattachés à la zone voisine qui partage la plus longue frontière commune. Au-delà, c'est une erreur de configuration. Le territoire doit être couvert à 99,99 %.
- Une station est rattachée à la zone qui la contient, sinon à la plus proche à moins de `emprise.tampon_m` (stations du littoral).

Vendée : 12 zones.

| Zone | Construction | Surface | SPI 3 mois | IPS | Débits |
|---|---|---|---|---|---|
| Sud-Vendée sédimentaire | FRGG034, FRGG041, FRGG042 | 971 km² | 0,25 | 0,50 | 0,25 |
| Marais poitevin | FRGG126, FRGG127 | 705 km² | 0,30 | 0,40 | 0,30 |
| Marais breton | FRGG017, FRGG025, FRGG031 | 576 km² | 0,30 | 0,40 | 0,30 |
| Île de Noirmoutier | FRGG036 | 50 km² | 0,40 | 0,60 | 0 |
| Île d'Yeu | FRGG035 | 24 km² | 0,40 | 0,60 | 0 |
| Bocage – 7 sous-zones | masses d'eau de socle × zones d'alerte superficielles (Lay et Lay réalimenté, Vie et Jaunay, Maines, Côtiers vendéens, Sèvre nantaise, Logne-Boulogne-Ognon, Vendée et Autize superficiels) | 297 à 1 465 km² | 0,40 | 0,15 | 0,45 |

- Les îles forment des zones à part entière. Faute de cours d'eau jaugé, leur indice composite repose sur le SPI et l'IPS.
- Le bocage (4 429 km²) est découpé par les zones d'alerte superficielles VigiEau, pour une lecture par bassin versant proche de celle des arrêtés de restriction.
- Le découpage est figé dans `data/referentiels/zones.parquet`, versionné par DVC. Il ne change que par une reconstruction volontaire des référentiels, par exemple après la révision d'un arrêté-cadre ou de l'état des lieux DCE.

## D6 — Remplissage des retenues d'eau potable

*2026-09-30 · issu du [spike n°6](spikes/06_retenues.md)*

**Constat.** En Vendée, 94 % de l'eau potable vient de retenues de surface. Leur remplissage est l'indicateur le plus suivi localement, mais il mêle apports naturels, prélèvements et gestion (réalimentation, transferts). Son historique est court : 13 retenues suivies chaque semaine depuis 2019.

**Décision.**

- Nouvelle source `retenues` : un relevé hebdomadaire par retenue (volume, capacité), stocké dans `data/raw/retenues/retenues_<annee>.parquet` (table `obs.retenue_semaine`). Les retenues entrent dans le référentiel des stations (source `retenue`), rattachées à leur zone.
- Source du territoire : la table ArcGIS publique du Département (`config/stations.yaml`), en l'absence d'accord formel de réutilisation. Le relevé archivé dans `data/` fait foi, même si le service disparaît. En repli, ou comme source principale pour un territoire qui n'en a pas, on utilise la couche nationale de la DREAL Bretagne, qui ne donne que la dernière semaine et que le pipeline archive chaque semaine. Les noms nationaux sont ramenés aux codes locaux par `alias_repli`.
- La semaine ISO se déduit de la **date** du relevé. Les numéros de semaine de la source ne suivent pas la norme ISO (écart dans 26 % des cas).
- La table du **volume total depuis 2012** n'est pas ingérée : elle est décalée d'une semaine par rapport à la somme des retenues sur une partie des années (jusqu'à 6,8 Mm³ d'écart), et sans date, on ne peut pas la réaligner. Le total est calculé par somme des retenues, à partir de 2019.
- **Affichage hors indice composite en V1**, comme ONDE : courbe de l'année comparée à l'enveloppe minimum, médiane et maximum de 2019–2025, par retenue et pour le total. L'indicateur relève de l'axe « tension » de la V3 (principe n°3 de la spec).

## D7 — Normales de référence

*2026-09-30*

**Décision.** Une période compte dans la référence selon un critère **par période**, et non par année entière. Le SPI d'une zone se calcule sur la **pluie moyenne de la zone** (option A). Paramètres dans `config/projet.yaml` (`indices`), calcul par `make reference`, résultats dans `data/normales/` (versionné par DVC).

| Indice | Échelle | Échantillon de référence | Normale stockée |
|---|---|---|---|
| SPI 1, 3 et 6 mois | zone | cumuls de pluie de 30, 91 et 182 jours terminés le dimanche de chaque semaine ISO, une valeur par année | par zone, fenêtre et semaine : paramètres d'une loi gamma (forme, échelle) et part de cumuls nuls `q0` |
| IPS | piézomètre | niveau moyen mensuel, un mois comptant s'il a au moins 10 jours de mesures | par station et mois : les moyennes mensuelles de référence |
| Indice de débit | station hydrométrique (séries raccordées, D4) | débit moyen sur 7 jours (au moins 5 jours renseignés), aux dates situées à ±15 jours du dimanche de la semaine ; une année compte si la moitié au moins de sa fenêtre est renseignée | par station et semaine : les valeurs de référence |

- **Pluie d'une zone** : moyenne des mailles SIM pondérée par la surface de chaque maille dans la zone. Standardiser après agrégation garde le SPI de zone sur l'échelle des 7 classes. La moyenne de SPI de mailles aurait une variance inférieure à 1, et les zones atteindraient rarement les classes extrêmes.
- **Période** : 1991–2020 si au moins 15 années y sont valides pour la période considérée. À défaut, toutes les années disponibles si elles sont au moins 15, avec `hors_reference = vrai` et la période effective dans `periode_ref` (SPEC §6.1). Sinon, pas de normale.
- La semaine ISO 53 utilise la normale de la semaine 52.
- La conversion en indice standardisé intervient au calcul hebdomadaire (étape 5). SPI : $\Phi^{-1}(q_0 + (1-q_0)\,F_\gamma(x))$. IPS et débit : rang de la valeur dans l'échantillon de référence, converti en valeur centrée réduite (approche non paramétrique).

Résultats (Vendée, 2026-09-30, après D8) : 1 872 normales de SPI (12 zones × 3 fenêtres × 52 semaines, toutes sur 1991–2020) ; IPS pour 37 piézomètres ; indice de débit pour 29 stations, dont 25 sur 1991–2020. Contrôle : les SPI-3 de la période de référence ont une moyenne de 0,000 et un écart-type de 1,000.

## D8 — Stations au fonctionnement modifié (ruptures)

*2026-09-30*

**Constat.** L'IPS suppose que la normale 1991–2020 décrit encore le comportement actuel d'une nappe. Plusieurs piézomètres montrent un changement durable de régime, sans lien avec le climat : travaux, modification des prélèvements ou du repère de mesure (non établi à ce jour). Au piézomètre de L'Épine (05068X0028/SP010), le niveau remonte de 2 m entre 2016 et 2021 et l'amplitude saisonnière diminue. Avec la normale 1991–2020, la station serait classée « très haute » en permanence, même en pleine sécheresse (100 % des mois de 2021–2025). Test de Pettitt sur les moyennes annuelles : 9 piézomètres sur 38 présentent une rupture significative (p < 0,01), tous sauf un à Noirmoutier ou dans le marais breton, avec des ruptures en 2011 et entre 2016 et 2021. Aucune rupture significative n'apparaît sur les 25 stations hydrométriques testées.

**Décision.**

- **Détection** à chaque `make reference` : test de Pettitt sur les moyennes annuelles des années complètes (niveau moyen ; logarithme du débit moyen), résultat dans `data/normales/ruptures.parquet`. Les ruptures significatives non traitées sont signalées dans le journal. Le test ne décide rien : il peut confondre une longue séquence sèche ou humide avec une rupture.
- **Traitement explicite** des ruptures confirmées, dans `config/stations.yaml` (`ruptures` : station, première année du nouveau régime, motif). La référence ne porte alors que sur les années à partir de la rupture. Elle est admise dès `annees_min_apres_rupture` ans (8, contre 15 en règle générale), toujours avec avertissement (`hors_reference`, colonne `rupture`). En deçà, la station n'a pas d'IPS, et sa courbe brute reste affichée.
- **Écartés** : retirer la tendance de toutes les séries (on effacerait aussi l'effet du changement climatique) ; remplacer 1991–2020 par une période glissante pour toutes les stations (la rupture resterait dans la période, et les stations saines perdraient la normale officielle) ; décaler les valeurs d'avant la rupture (l'amplitude change aussi, pas seulement le niveau).

Liste au 2026-09-30 :

| Station | Secteur | Nouveau régime depuis | Effet |
|---|---|---|---|
| 05341X0104/SF7, 05342X0034/F4, 05076X0001/S | marais breton, nappe captive | 2011 (saut simultané de +0,3 à +0,7 m) | IPS sur 2011–2025 |
| 05342X0078/FORAGE | marais breton | 2016 (+0,3 m) | IPS sur 2016–2025 |
| 05068X0028/SP010, 05068X0054/F, 05334X0011/SF7 | Noirmoutier | 2021 (remontée progressive depuis 2016) | pas d'IPS avant 2028 : le composite de l'île repose sur le SPI |

Ruptures signalées et non retenues : 05342X0073/F (creux en 2017–2022 sans changement de régime), 05863X0203/F (hausse modérée de +0,3 m en 2010, sans dérive marquée des classes récentes). L'origine des ruptures de Noirmoutier et du marais breton reste à documenter auprès du BRGM ou des gestionnaires locaux.

## D9 — Indices de la semaine

*2026-10-01*

**Décision.** Les indices d'une semaine ISO sont calculés au dimanche qui la termine, avec les seules mesures datées de ce dimanche ou d'avant. Calcul par `make indices` (tout l'historique depuis `indices.historique_debut`, 1991) ou pour une plage de semaines ; résultats dans `data/indices/` (un fichier par table et par année ISO, versionné par DVC), chargés dans `idx.*`.

| Indice | Échelle | Valeur de la semaine |
|---|---|---|
| SPI 1, 3 et 6 mois | zone | cumul de pluie de la zone terminé le dimanche ; $\Phi^{-1}(q_0 + (1-q_0)F_\gamma(x))$ avec la normale de la semaine (D7), bornée à ±3 : un cumul nul sans précédent dans la référence donnerait −∞, et au-delà de 3 la loi gamma ajustée sur 30 ans n'est plus informative. La borne touche 0,2 % des valeurs de 1991–2026 (142 sur 67 140), dont 101 en 2026, année très sèche ; la classe n'en dépend pas |
| IPS | piézomètre | moyenne du **mois en cours** s'il compte au moins `jours_min_mois` (10) jours de mesures jusqu'au dimanche, sinon du dernier mois qui les atteint (méthode du BRGM, cohérente avec les normales mensuelles ; l'IPS ne bouge pas pendant les 9 premiers jours du mois) |
| Débit | station (séries raccordées, D4) | Q7 terminé le dimanche ; sans Q7 ce jour-là, pas d'indice |
| ONDE | zone | part des stations observées en écoulement non visible (modalité 2) ou en assec (3), par campagne, rattachée à la semaine de la campagne ; la plus récente l'emporte si deux campagnes tombent la même semaine. Sans classe, hors composite (D3) |

- **Rang → valeur standardisée** (IPS, débit) : la valeur de la semaine est ajoutée à l'échantillon de référence ; probabilité au non-dépassement de Gringorten, $(i - 0{,}44)/(n + 0{,}12)$ sur les $n+1$ valeurs, les ex aequo prenant le rang moyen ; puis $\Phi^{-1}$. Les valeurs restent finies au-delà des extrêmes de la référence, et les classes 1 et 7 restent accessibles avec un échantillon court (à 9 ans : ±1,60).
- **Fraîcheur (D1)** : `date_mesure` est la date de la dernière mesure du mois retenu ; `dans_composite` est vrai si elle a moins de `fraicheur_max_jours` (45) jours au dimanche. Au-delà de `ingestion.piezo_inactif_apres_jours` (365) jours, station hors service : pas d'indice.
- **Ruptures (D8)** : la normale ne décrit que le nouveau régime ; les semaines antérieures à l'année de rupture n'ont pas d'indice.
- **Indice de zone** (IPS, débit) : moyenne des indices des stations de la zone qui entrent au composite ; liste des stations dans `detail`.
- **Composite** : moyenne pondérée des composantes de poids non nul disponibles (`spi_3`, `ips`, `debit`), poids renormalisés ; `detail` donne chaque composante (valeur, poids, poids appliqué), les composantes manquantes, leur nombre et l'indicateur `partiel`.
- **`version_methodo`** : identifiant de la dernière décision en vigueur (`indices.version_methodo`, ici « D9 »), à changer à chaque nouvelle décision. Le numéro de commit n'est pas utilisé : il changerait à chaque commit et deux exécutions sur la même semaine ne donneraient plus le même résultat (SPEC §12, n°10).
- **Historique** : les semaines passées sont calculées avec les données publiées depuis. Elles sont plus complètes que ce qui était disponible en temps réel, notamment en piézométrie publiée par lots (D1) : 97 % des IPS de 1991–2020 entrent au composite, contre la moitié en 2026-W39.

Contrôles (Vendée, 1991–2020, 1 566 semaines) :

| | Écart-type | Classe 1 | Classe 7 |
|---|---|---|---|
| attendu pour un indice standardisé | 1 | 10 % | 10 % |
| SPI 3 mois par zone | 1,00 | 11,3 % | 10,0 % |
| IPS par station / par zone | 0,92 / 0,85 | 8,6 % / 5,9 % | 9,6 % / 7,8 % |
| Débit par station / par zone | 0,97 / 0,93 | 9,1 % / 8,2 % | 9,6 % / 9,2 % |
| Composite | 0,79 (marais breton) à 1,00 (Noirmoutier) | 5,4 % à 11,8 % | 5,6 % à 10,3 % |

**À réexaminer.** Une moyenne d'indices varie moins que chacun d'eux : plus une zone compte de stations ou de composantes, plus les classes extrêmes y sont rares (Sud-Vendée : 14 piézomètres en moyenne, IPS de zone en classe 1 4 % du temps ; composite en classe 1 5,7 % du temps). Pistes : restandardiser l'indice de zone et le composite sur leur propre historique 1991–2020, ou l'accepter et le documenter. À trancher avec la validation sur les sécheresses passées (2011, 2017, 2019, 2022).

## Règles issues des données

- **Piézométrie : seul `niveau_nappe_eau` est ingéré comme mesure.** Dans Hub'Eau, `profondeur_nappe` est une copie du niveau NGF pour 50 stations sur 53. La colonne `obs.piezo_jour.profondeur` est calculée par `altitude_station − niveau_nappe_eau` quand l'altitude est connue (différente de `-999`), sinon laissée vide.

### Ingestion des observations (`data/raw/`)

| Table | Source | Contenu des colonnes |
|---|---|---|
| `obs.piezo_jour` | Hub'Eau `chroniques` | `niveau_ngf` = `niveau_nappe_eau` ; `profondeur` = altitude du repère − niveau ; `qualification` = `statut` (donnée brute, contrôlée niveau 1 ou 2, interprétée) |
| `obs.debit_jour` | Hub'Eau `obs_elab`, grandeur `QmnJ` | `qmj_ls` en l/s ; `qualification` = `libelle_statut` (donnée validée, pré-validée, brute) ; les stations successives d'un même site restent distinctes, leur raccordement (D4) intervient au calcul des indices |
| `obs.onde` | Hub'Eau `observations` et `campagnes` | `modalite` = `code_ecoulement` (1 visible, 1a acceptable, 1f faible, 2 non visible, 3 assec) ; `type_campagne` = usuelle ou complémentaire |
| `obs.meteo_jour` | SIM quotidienne, un fichier par année plus les 60 derniers jours | `precip_mm` = `PRELIQ` + `PRENEI` ; `etp_mm` = `ETP` ; `swi` = `SWI` en fraction ; historique à partir de l'année précédant la période de référence (1990) |
| `obs.retenue_semaine` | voir D6 | volume et capacité en m³ |

- Historique complet pour Hub'Eau ; en suivi hebdomadaire, réingestion des `fenetre_reingestion_jours` derniers jours. Exception pour les piézomètres, publiés par lots (D1) : une station dont la dernière mesure en stock est plus ancienne est relue depuis cette mesure (au 2026-10-01, 8 piézomètres suivis sur 39 n'avaient aucune mesure depuis plus de 90 jours). Une valeur corrigée à la source remplace l'ancienne, une valeur inchangée garde sa date d'ingestion.
- Une station ou une source en échec est consignée dans le rapport d'exécution sans bloquer les autres (SPEC §7.2).

## Points ouverts

- Faible fréquence des classes extrêmes dans les indices de zone et le composite (D9, « À réexaminer »).
