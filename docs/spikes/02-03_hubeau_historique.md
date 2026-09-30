# Spikes V0 n°2 et n°3 — Historique Hub'Eau et période de référence

Date : 2026-09-29 · Département : 85 · Script : [`hubeau_historique.py`](hubeau_historique.py) · Données : [`hubeau_historique.csv`](hubeau_historique.csv) (une ligne par station)

## Questions

1. Profondeur réelle de l'historique des chroniques piézométriques et des débits `QmnJ` en Vendée ; comportement de la pagination sur un gros volume.
2. Nombre de stations disposant d'au moins 15 ans de données sur la référence 1991–2020, par zone.

## Méthode

Téléchargement de l'historique complet des 56 piézomètres (`chroniques`) et des 41 stations hydrométriques (`obs_elab`, `QmnJ`), sans filtre de date.

Critères d'**année exploitable**, provisoires, propres au spike :

- piézométrie : au moins 10 mois contenant une mesure (l'IPS repose sur des moyennes mensuelles) ;
- débits : au moins 330 jours de `QmnJ`.

Une station est dite **active** si sa dernière donnée a moins d'un an.

## Résultats

### Pagination et volumes

| | Piézométrie `chroniques` | Hydrométrie `obs_elab` |
|---|---|---|
| Pagination | `page` × `size`, **plafond de 20 000 résultats** par requête (`page * size <= 20000`) | curseur (`next`), sans plafond de profondeur ; `size` ≤ 20 000 |
| Plus longue série | 12 950 mesures | 21 455 `QmnJ` (Lay à Saint-Prouant, depuis 1968) |
| Conséquence | une requête par station suffit aujourd'hui ; découper par période au-delà de 20 000 mesures (vers 2045 pour les plus longues) | une à deux pages par station |
| Durée, historique complet | 93 s pour 56 stations | 850 s pour 41 stations |

- Le nombre de lignes reçues correspond au `count` annoncé pour toutes les stations, y compris au-delà de 20 000 lignes avec le curseur.
- Hub'Eau répond de façon irrégulière : une requête sur `obs_elab` par code de **site** a expiré sans réponse. Il faut interroger par code de **station**, avec reprises (déjà prévu, §7.2).
- Le paramètre `sort=desc` est ignoré par `obs_elab`.
- L'ingestion complète de l'historique prend environ 15 minutes ; la réingestion hebdomadaire sur 90 jours sera de l'ordre de la minute.

### Piézométrie

| Zone (provisoire, d'après la masse d'eau) | Stations | Actives | ≥ 15 ans sur 1991–2020 | dont mesure < 14 j | dont mesure < 60 j |
|---|---|---|---|---|---|
| Sud-Vendée (Lias-Dogger libre et captif, Chantonnay) | 25 | 21 | 20 | 10 | 18 |
| Marais breton (tertiaire) | 13 | 10 | 6 | 1 | 1 |
| Socle (bassins versants Sèvre nantaise, Vie, Auzance, socle du marais poitevin) | 9 | 6 | 5 | 2 | 3 |
| Îles (Noirmoutier, Yeu) | 5 | 4 | 3 | 1 | 1 |
| Masse d'eau non renseignée | 4 | 1 | 1 | 1 | 1 |
| **Total** | **56** | **42** | **35** | **15** | **24** |

- Séries longues et denses : pas de temps journalier (pas médian 1 jour), débuts entre 1985 et 1996 pour la majorité. 35 stations ont au moins 15 ans exploitables sur 1991–2020, dont 8 les 30 ans complets.
- **Aucune station de Vendée n'est présente dans `chroniques_tr`** (temps réel).
- **Mises à jour par lots** : la donnée est journalière, mais publiée avec retard et par paquets. Au 29/09, les dernières mesures datent du 18/09 (16 stations), des 10–11/08 (8 stations) ou de mars 2026 (presque tout le marais breton et Noirmoutier). Retard médian des stations actives : 49 jours.
- **`profondeur_nappe` est inutilisable** : pour 50 stations sur 53, ce champ est une copie de `niveau_nappe_eau`. Les valeurs sont toujours inférieures à l'altitude du repère, et négatives sur le littoral : ce sont des cotes NGF, pas des profondeurs. Seul `niveau_nappe_eau` doit être ingéré comme mesure ; une profondeur éventuelle se calcule par `altitude_station − niveau`, sauf quand l'altitude vaut `-999`.
- 95 % des mesures sont contrôlées (niveau 1 ou 2) et 5 % sont brutes, surtout sur les stations récentes ou anciennes peu suivies.

### Débits

- 30 stations en service sur 41 ; 19 cumulent au moins 15 ans sur la référence et une donnée récente, 8 ont les 30 ans complets.
- **Retard de 2 jours** pour la plupart des stations en service, 9 jours au plus, sauf l'Autise à Saint-Hilaire-des-Loges (71 jours) et la Vendée à Pissotte (55 jours). Les valeurs récentes ne sont pas encore validées (part de données validées : médiane 85 %, de 18 % à 97 % selon la station), d'où l'intérêt de la fenêtre de réingestion de 90 jours.
- Trois stations en service n'ont aucun `QmnJ` : Sèvre niortaise à Maillé, estuaire du Lay et Sèvre nantaise à Saint-Laurent-sur-Sèvre. Ce sont probablement des stations de hauteur seule.
- **Chaînage de stations** : sur un même site, une station ancienne peut être remplacée par une nouvelle. Exemple : Sèvre nantaise à Tiffauges, `M711241010` de 1967 à 2022 puis `M711241020` depuis 2005. Raccorder les deux séries donne une référence longue et une donnée à jour.

### ONDE (hors périmètre du spike, relevé au passage)

- 30 stations, 174 campagnes, **depuis 2012 seulement** : 14 saisons, moins que le minimum de 15 ans.
- En Vendée, les campagnes vont d'**avril à novembre**. Les campagnes usuelles sont mensuelles, et des campagnes complémentaires, jusqu'à tous les 10 jours, s'ajoutent en période de sécheresse.

## Conséquences et décisions à prendre

| # | Constat | Proposition | Nature |
|---|---|---|---|
| 1 | La fraîcheur des données piézométriques varie de 11 jours à 7 mois selon la station | Calculer l'IPS sur le dernier mois disponible, stocker la date de la dernière mesure, et n'intégrer une station au composite de la semaine que si sa donnée a moins de `fraicheur_max_jours` (paramètre de configuration, par exemple 45 jours) | Méthodologie |
| 2 | Marais breton : 6 stations éligibles, mais une seule à jour | Conséquence du point 1 : l'IPS du marais breton sera souvent absent ou « partiel ». Poids renormalisés comme prévu au §6.4 | Méthodologie |
| 3 | Le socle a 5 piézomètres éligibles, dont 2 à 3 à jour, alors que la spec le dit « quasiment non couvert » et lui donne un poids IPS nul | Garder 0 en V1, ou donner un poids faible (0,10–0,15) à l'IPS du bocage | Méthodologie |
| 4 | ONDE n'a que 14 saisons | Standardisation impossible avec `annees_min: 15` : projeter la part d'assecs sur les 7 classes par des seuils fixes dans la configuration | Méthodologie |
| 5 | Saison ONDE d'avril à novembre | Corriger le §4.3 de la spec | Documentation |
| 6 | `profondeur_nappe` est une copie du niveau | Ingérer `niveau_nappe_eau` seul ; `obs.piezo_jour.profondeur` calculée par `altitude − niveau` quand l'altitude est connue, sinon nulle | Schéma (colonne conservée) |
| 7 | Chaînage de stations hydrométriques sur un même site | Raccorder les séries d'un même site dans la configuration (liste explicite, pas d'automatisme) | Méthodologie |
| 8 | Critères d'année exploitable (10 mois, 330 jours) | Les fixer dans `docs/methodologie.md` et `config/` | Méthodologie |
| 9 | Stations sans masse d'eau renseignée (4), et stations hydrométriques non rattachées aux zones | Le rattachement aux zones passe par la géométrie : nécessite le découpage des zones (BDLISA ou zones d'alerte) | Référentiels |

Décisions du 2026-09-30 ([méthodologie](../methodologie.md)) : point 1 adopté (D1, 45 jours) ; point 3, poids IPS de 0,15 dans le bocage (D2) ; point 4, ONDE hors composite en V1 plutôt que des seuils fixes (D3) ; point 7 adopté, raccordement de Tiffauges seul (D4). Points 6 et 8 : règle d'ingestion consignée et critère d'année exploitable encore ouvert.
