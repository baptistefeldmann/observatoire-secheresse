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

## Règles issues des données

- **Piézométrie : seul `niveau_nappe_eau` est ingéré comme mesure.** Dans Hub'Eau, `profondeur_nappe` est une copie du niveau NGF pour 50 stations sur 53. La colonne `obs.piezo_jour.profondeur` est calculée par `altitude_station − niveau_nappe_eau` quand l'altitude est connue (différente de `-999`), sinon laissée vide.

## Points ouverts

- **Critère d'année exploitable** pour la période de référence. Le spike a utilisé, à titre provisoire, au moins 10 mois avec une mesure pour la piézométrie et au moins 330 jours de `QmnJ` pour les débits. À fixer avant `make reference`.
