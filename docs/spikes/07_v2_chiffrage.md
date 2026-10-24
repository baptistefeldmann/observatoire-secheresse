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

1. **Q9 est à reprendre** : pas de seuil fixe sur VV. Méthode proposée : détection par changement (Δ ≤ −3 dB et VV ≤ −16 dB, référence d'été par pixel et par orbite relative), **avec validation permanente par Sentinel-2** sur les dates claires. Les surfaces s'écartent de 20 % au plus de celles de Sentinel-2 sur 3 comparaisons, mais le bruit d'été est de plusieurs centaines d'hectares : à soustraire ou à publier avec une incertitude.
2. **Orbites** : exclure la 132 (l'eau n'y est pas visible), surveiller la 154.
3. **Valider davantage** : au moins une dizaine de dates claires de Sentinel-2 sur plusieurs hivers, avant de figer la méthode.
4. **Offset BOA** : confirmé indispensable ; **scènes à baseline inconnue écartées** ; seuil d'alerte de dérive proposé à 0,03 de NDVI.
5. **Médiane** (4.2) et **NDMI en plus du NDVI** (4.3) : confirmés.
6. **Classes** : 7 classes de forêt et 9 de culture (section 1), toutes assez grandes.

## 6. Ce qui reste à faire

- **Réseau maritime** (tronçons hydrographiques aval des limites de salure des eaux et transversales de la mer) et **contrôle de marée** par la hauteur d'eau du SHOM : non faits ; ils dépendent de la méthode de détection de l'eau, à fixer d'abord.
- **Masque d'eau permanente de Sentinel-1** sur 2015-2025 : non fait ; en 2024, Sentinel-2 en voit 251 ha dans le Marais poitevin.
- **Millésime de la BD Forêt V2** pour la Vendée.
- **Validation Sentinel-1 / Sentinel-2** sur plus de dates et sur le Marais breton.
