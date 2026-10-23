# Validation des indices par les arrêtés sécheresse — Vendée

*Rapport généré par `make validation` : ne pas modifier à la main.*

Arrêtés VigiEau jusqu'à la semaine 2026-W42 ; indices en version de méthode D14.

## Données comparées

- **Arrêtés** : 198 arrêtés du département, dont 173 listent leurs zones d'alerte (depuis 2012). Une semaine prend le niveau en vigueur le dimanche ; une zone prend le niveau le plus sévère de ses zones d'alerte.
- **Saison** : semaines 18 à 44, années 2012 à 2026 ; 10 zones, 4030 semaines-zones.
- **Zones sans zone d'alerte rattachée** (hors comparaison) : Île de Noirmoutier, Île d'Yeu.
- **Zones d'alerte non rattachées** : Autres nappes d'eau douce (SOU), NAPPE PLAINE-BOCAGE (SOU).

Un arrêté se déclenche quand un débit ou un niveau de nappe passe sous un **seuil fixe**,
alors que l'indice compare chaque semaine à la **normale de la saison**. Les petits cours
d'eau passent sous leur seuil presque chaque fin d'été : un désaccord en août-septembre
d'une année normale est attendu. Les arrêtés sont aussi levés avec retard après les
pluies.

## Par année

| Année | Alerte ou plus | Crise | Composite moyen | Classes 1-2 | Classes 4 à 7 |
|---|---|---|---|---|---|
| 2012 | 33 % | 16 % | 0,38 | 4 % | 83 % |
| 2013 | 29 % | 23 % | 0,23 | 1 % | 81 % |
| 2014 | 23 % | 13 % | 0,61 | 1 % | 89 % |
| 2015 | 31 % | 11 % | 0,41 | 2 % | 89 % |
| 2016 | 37 % | 23 % | −0,19 | 37 % | 57 % |
| 2017 | 75 % | 53 % | −0,79 | 40 % | 8 % |
| 2018 | 51 % | 26 % | 0,01 | 24 % | 65 % |
| 2019 | 64 % | 50 % | −0,52 | 25 % | 30 % |
| 2020 | 45 % | 25 % | 0,48 | 3 % | 86 % |
| 2021 | 48 % | 21 % | 0,03 | 17 % | 63 % |
| 2022 | 81 % | 58 % | −1,21 | 77 % | 1 % |
| 2023 | 57 % | 32 % | −0,23 | 12 % | 46 % |
| 2024 | 15 % | 0 % | 1,43 | 0 % | 100 % |
| 2025 | 56 % | 25 % | −0,41 | 16 % | 34 % |
| 2026 | 74 % | 54 % | −1,55 | 86 % | 6 % |

Part des semaines-zones de la saison. Corrélation de rang entre années (part sous alerte
et composite moyen) : **−0,92** (−1 : les années les plus restreintes sont les plus sèches pour l'indice).

## Par zone

| Zone | Semaines | Alerte ou plus | AUC composite | SPI 3 mois | IPS | Débit |
|---|---|---|---|---|---|---|
| Bocage - Côtiers vendéens | 403 | 62 % | 0,74 | 0,71 | 0,64 | 0,74 |
| Bocage - Lay | 403 | 50 % | 0,80 | 0,77 | 0,72 | 0,78 |
| Bocage - Logne, Boulogne, Ognon et Grand Lieu | 403 | 67 % | 0,75 | 0,73 |  | 0,73 |
| Bocage - Maines | 403 | 45 % | 0,75 | 0,73 | 0,71 | 0,69 |
| Bocage - Sèvre nantaise | 403 | 39 % | 0,76 | 0,73 | 0,53 | 0,76 |
| Bocage - Vendée | 403 | 47 % | 0,81 | 0,78 |  | 0,78 |
| Bocage - Vie et Jaunay | 403 | 63 % | 0,71 | 0,71 | 0,69 | 0,68 |
| Marais breton | 403 | 53 % | 0,78 | 0,77 | 0,72 | 0,74 |
| Marais poitevin | 403 | 30 % | 0,82 | 0,74 | 0,83 |  |
| Sud-Vendée sédimentaire | 403 | 23 % | 0,83 | 0,79 | 0,80 | 0,83 |
| **Ensemble** | 4030 | 48 % | **0,76** | 0,72 | 0,69 | 0,73 |

AUC : probabilité qu'une semaine sous alerte (ou plus) ait une valeur plus sèche qu'une
semaine sans alerte (0,5 : hasard ; 1 : séparation parfaite). Vide : composante absente.

## Classes du composite selon le niveau de restriction

| Classe | aucun (1777) | vigilance (326) | alerte (421) | alerte renforcée (358) | crise (1148) |
|---|---|---|---|---|---|
| 1 | 4 % | 8 % | 13 % | 9 % | 23 % |
| 2 | 6 % | 10 % | 15 % | 15 % | 19 % |
| 3 | 14 % | 18 % | 29 % | 28 % | 28 % |
| 4 | 19 % | 25 % | 17 % | 21 % | 17 % |
| 5 | 26 % | 27 % | 16 % | 21 % | 9 % |
| 6 | 14 % | 9 % | 7 % | 4 % | 2 % |
| 7 | 17 % | 5 % | 4 % | 3 % | 1 % |

Part de chaque classe parmi les semaines-zones d'un niveau (effectif entre parenthèses).

## Semaines en crise avec un composite normal ou plus humide

335 semaines-zones sur 1148 en crise (29 %).

| Zone | Semaines |
|---|---|
| Bocage - Logne, Boulogne, Ognon et Grand Lieu | 74 |
| Bocage - Vie et Jaunay | 72 |
| Bocage - Côtiers vendéens | 66 |
| Marais breton | 34 |
| Bocage - Vendée | 29 |
| Bocage - Lay | 22 |
| Bocage - Maines | 22 |
| Bocage - Sèvre nantaise | 12 |
| Marais poitevin | 4 |

| Mois | Semaines |
|---|---|
| juin | 2 |
| juillet | 18 |
| août | 114 |
| septembre | 119 |
| octobre | 81 |
| novembre | 1 |
