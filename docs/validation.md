# Validation des indices par les arrêtés sécheresse — Vendée

*Rapport généré par `make validation` : ne pas modifier à la main.*

Arrêtés VigiEau jusqu'à la semaine 2026-W40 ; indices en version de méthode D10.

## Données comparées

- **Arrêtés** : 198 arrêtés du département, dont 173 listent leurs zones d'alerte (depuis 2012). Une semaine prend le niveau en vigueur le dimanche ; une zone prend le niveau le plus sévère de ses zones d'alerte.
- **Saison** : semaines 18 à 44, années 2012 à 2026 ; 10 zones, 4010 semaines-zones.
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
| 2012 | 33 % | 16 % | 0,42 | 2 % | 85 % |
| 2013 | 29 % | 23 % | 0,27 | 1 % | 83 % |
| 2014 | 23 % | 13 % | 0,65 | 0 % | 90 % |
| 2015 | 31 % | 11 % | 0,44 | 2 % | 88 % |
| 2016 | 37 % | 23 % | −0,15 | 34 % | 57 % |
| 2017 | 75 % | 53 % | −0,75 | 37 % | 11 % |
| 2018 | 51 % | 26 % | 0,03 | 24 % | 66 % |
| 2019 | 64 % | 50 % | −0,48 | 23 % | 31 % |
| 2020 | 45 % | 25 % | 0,52 | 3 % | 86 % |
| 2021 | 48 % | 21 % | 0,05 | 16 % | 62 % |
| 2022 | 81 % | 58 % | −1,17 | 71 % | 1 % |
| 2023 | 57 % | 32 % | −0,21 | 11 % | 47 % |
| 2024 | 15 % | 0 % | 1,46 | 0 % | 100 % |
| 2025 | 56 % | 25 % | −0,39 | 15 % | 36 % |
| 2026 | 72 % | 50 % | −1,56 | 82 % | 7 % |

Part des semaines-zones de la saison. Corrélation de rang entre années (part sous alerte
et composite moyen) : **−0,92** (−1 : les années les plus restreintes sont les plus sèches pour l'indice).

## Par zone

| Zone | Semaines | Alerte ou plus | AUC composite | SPI 3 mois | IPS | Débit |
|---|---|---|---|---|---|---|
| Bocage - Côtiers vendéens | 401 | 62 % | 0,74 | 0,71 | 0,64 | 0,74 |
| Bocage - Lay | 401 | 50 % | 0,80 | 0,77 | 0,70 | 0,78 |
| Bocage - Logne, Boulogne, Ognon et Grand Lieu | 401 | 66 % | 0,75 | 0,72 |  | 0,73 |
| Bocage - Maines | 401 | 45 % | 0,75 | 0,72 | 0,70 | 0,69 |
| Bocage - Sèvre nantaise | 401 | 39 % | 0,76 | 0,73 | 0,58 | 0,76 |
| Bocage - Vendée | 401 | 46 % | 0,80 | 0,77 |  | 0,78 |
| Bocage - Vie et Jaunay | 401 | 63 % | 0,71 | 0,70 | 0,69 | 0,68 |
| Marais breton | 401 | 53 % | 0,78 | 0,77 | 0,72 | 0,74 |
| Marais poitevin | 401 | 30 % | 0,78 | 0,74 | 0,79 |  |
| Sud-Vendée sédimentaire | 401 | 23 % | 0,80 | 0,79 | 0,73 | 0,83 |
| **Ensemble** | 4010 | 48 % | **0,76** | 0,72 | 0,69 | 0,73 |

AUC : probabilité qu'une semaine sous alerte (ou plus) ait une valeur plus sèche qu'une
semaine sans alerte (0,5 : hasard ; 1 : séparation parfaite). Vide : composante absente.

## Classes du composite selon le niveau de restriction

| Classe | aucun (1777) | vigilance (326) | alerte (419) | alerte renforcée (358) | crise (1130) |
|---|---|---|---|---|---|
| 1 | 4 % | 6 % | 11 % | 9 % | 22 % |
| 2 | 5 % | 10 % | 13 % | 16 % | 17 % |
| 3 | 14 % | 18 % | 29 % | 26 % | 31 % |
| 4 | 19 % | 24 % | 18 % | 20 % | 18 % |
| 5 | 26 % | 27 % | 18 % | 22 % | 9 % |
| 6 | 14 % | 9 % | 7 % | 4 % | 2 % |
| 7 | 18 % | 6 % | 4 % | 3 % | 1 % |

Part de chaque classe parmi les semaines-zones d'un niveau (effectif entre parenthèses).

## Semaines en crise avec un composite normal ou plus humide

344 semaines-zones sur 1130 en crise (30 %).

| Zone | Semaines |
|---|---|
| Bocage - Logne, Boulogne, Ognon et Grand Lieu | 74 |
| Bocage - Vie et Jaunay | 72 |
| Bocage - Côtiers vendéens | 66 |
| Marais breton | 34 |
| Bocage - Vendée | 29 |
| Bocage - Lay | 25 |
| Bocage - Maines | 22 |
| Bocage - Sèvre nantaise | 14 |
| Marais poitevin | 8 |

| Mois | Semaines |
|---|---|
| juin | 2 |
| juillet | 18 |
| août | 114 |
| septembre | 126 |
| octobre | 83 |
| novembre | 1 |
