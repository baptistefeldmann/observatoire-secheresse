# Validation des indices par les arrêtés sécheresse — Vendée

*Rapport généré par `make validation` : ne pas modifier à la main.*

Arrêtés VigiEau jusqu'à la semaine 2026-W40 ; indices en version de méthode D9.

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
| 2012 | 33 % | 16 % | 0,38 | 1 % | 86 % |
| 2013 | 29 % | 23 % | 0,25 | 0 % | 85 % |
| 2014 | 23 % | 13 % | 0,57 | 0 % | 92 % |
| 2015 | 31 % | 11 % | 0,39 | 1 % | 91 % |
| 2016 | 37 % | 23 % | −0,16 | 33 % | 58 % |
| 2017 | 75 % | 53 % | −0,65 | 26 % | 12 % |
| 2018 | 51 % | 26 % | 0,03 | 23 % | 68 % |
| 2019 | 64 % | 50 % | −0,43 | 17 % | 35 % |
| 2020 | 45 % | 25 % | 0,46 | 2 % | 87 % |
| 2021 | 48 % | 21 % | 0,04 | 15 % | 63 % |
| 2022 | 81 % | 58 % | −1,00 | 64 % | 2 % |
| 2023 | 57 % | 32 % | −0,18 | 7 % | 51 % |
| 2024 | 15 % | 0 % | 1,21 | 0 % | 100 % |
| 2025 | 56 % | 25 % | −0,35 | 10 % | 40 % |
| 2026 | 72 % | 50 % | −1,34 | 82 % | 7 % |

Part des semaines-zones de la saison. Corrélation de rang entre années (part sous alerte
et composite moyen) : **−0,92** (−1 : les années les plus restreintes sont les plus sèches pour l'indice).

## Par zone

| Zone | Semaines | Alerte ou plus | AUC composite | SPI 3 mois | IPS | Débit |
|---|---|---|---|---|---|---|
| Bocage - Côtiers vendéens | 401 | 62 % | 0,74 | 0,71 | 0,64 | 0,74 |
| Bocage - Lay | 401 | 50 % | 0,80 | 0,77 | 0,70 | 0,78 |
| Bocage - Logne, Boulogne, Ognon et Grand Lieu | 401 | 66 % | 0,75 | 0,72 |  | 0,73 |
| Bocage - Maines | 401 | 45 % | 0,74 | 0,72 | 0,70 | 0,69 |
| Bocage - Sèvre nantaise | 401 | 39 % | 0,76 | 0,73 | 0,58 | 0,76 |
| Bocage - Vendée | 401 | 46 % | 0,80 | 0,77 |  | 0,78 |
| Bocage - Vie et Jaunay | 401 | 63 % | 0,71 | 0,70 | 0,69 | 0,68 |
| Marais breton | 401 | 53 % | 0,78 | 0,77 | 0,72 | 0,74 |
| Marais poitevin | 401 | 30 % | 0,78 | 0,74 | 0,79 |  |
| Sud-Vendée sédimentaire | 401 | 23 % | 0,81 | 0,79 | 0,73 | 0,83 |
| **Ensemble** | 4010 | 48 % | **0,75** | 0,72 | 0,69 | 0,73 |

AUC : probabilité qu'une semaine sous alerte (ou plus) ait une valeur plus sèche qu'une
semaine sans alerte (0,5 : hasard ; 1 : séparation parfaite). Vide : composante absente.

## Classes du composite selon le niveau de restriction

| Classe | aucun (1777) | vigilance (326) | alerte (419) | alerte renforcée (358) | crise (1130) |
|---|---|---|---|---|---|
| 1 | 2 % | 3 % | 8 % | 5 % | 16 % |
| 2 | 5 % | 10 % | 13 % | 16 % | 18 % |
| 3 | 14 % | 21 % | 32 % | 28 % | 34 % |
| 4 | 21 % | 25 % | 19 % | 23 % | 20 % |
| 5 | 30 % | 28 % | 20 % | 23 % | 9 % |
| 6 | 15 % | 9 % | 7 % | 3 % | 2 % |
| 7 | 13 % | 3 % | 2 % | 2 % | 1 % |

Part de chaque classe parmi les semaines-zones d'un niveau (effectif entre parenthèses).

## Semaines en crise avec un composite normal ou plus humide

368 semaines-zones sur 1130 en crise (33 %).

| Zone | Semaines |
|---|---|
| Bocage - Logne, Boulogne, Ognon et Grand Lieu | 83 |
| Bocage - Vie et Jaunay | 74 |
| Bocage - Côtiers vendéens | 69 |
| Marais breton | 37 |
| Bocage - Vendée | 29 |
| Bocage - Lay | 28 |
| Bocage - Maines | 25 |
| Bocage - Sèvre nantaise | 14 |
| Marais poitevin | 9 |

| Mois | Semaines |
|---|---|
| juin | 2 |
| juillet | 21 |
| août | 121 |
| septembre | 134 |
| octobre | 89 |
| novembre | 1 |
