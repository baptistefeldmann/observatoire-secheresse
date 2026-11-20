"""[V2] Rapports de qualité et contrôle de dérive des composites de Sentinel-2 (D15, point 5).

Lit `rasters/mensuel/AAAA-MM/` (rapport, plans, médianes des classes stables par plan) et écrit dans
`data/satellite/` (GeoParquet de référence, versionné par DVC) :

- `composites_rapport.parquet` : une ligne par mois (scènes trouvées, écartées, plans, pixels
  jamais valides, observations moyennes) ;
- `composites_plans.parquet` : un plan (jour et offset) par ligne, avec plateforme et baseline ;
- `derive_cibles.parquet` : médiane de NDVI et de NDMI de chaque classe stable par plan ;
- `derive_groupes.parquet` : résidu médian de chaque plateforme (2A, 2B, 2C) et de chaque offset
  (baselines avant et depuis 04.00), par classe et par année ; le résidu d'un plan est son écart à
  la médiane des plans voisins (± `derive_fenetre_jours`), ce qui annule la phénologie ;
- `derive_ecarts.parquet` : écart entre les groupes d'une même année ; `anormal` au-delà de
  `satellite.composites.seuil_derive`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import Config
from pipeline.raster.composite import dossier_mensuel, dossier_satellite


def _lire(config: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rapports, plans, derives = [], [], []
    for dossier in sorted(p for p in dossier_mensuel(config).glob("[0-9]*-[0-9]*") if p.is_dir()):
        fichier = dossier / "rapport.json"
        if not fichier.is_file():
            continue
        rapports.append(json.loads(fichier.read_text(encoding="utf-8")))
        plans.append(pd.read_parquet(dossier / "plans.parquet").assign(mois=dossier.name))
        derives.append(pd.read_parquet(dossier / "derive.parquet").assign(mois=dossier.name))
    if not rapports:
        raise FileNotFoundError("aucun composite : lancer `make composites`")
    return (
        pd.DataFrame(rapports),
        pd.concat(plans, ignore_index=True),
        pd.concat(derives, ignore_index=True),
    )


def residus(derive: pd.DataFrame, fenetre_jours: int, couverture_min: float) -> pd.DataFrame:
    """Écart d'indice de chaque plan à ses voisins de ± `fenetre_jours`, pour chaque classe stable.

    Comparer des plans de dates différentes mélange la dérive radiométrique et la phénologie : on
    retranche donc à chaque plan la médiane des autres plans voisins (au moins deux), de toutes
    plateformes. Les plans qui ne voient pas `couverture_min` de la classe (nuages) sont écartés."""
    colonnes = ["classe", "date", "annee", "plateformes", "offset", "residu_ndvi", "residu_ndmi"]
    if derive.empty:
        return pd.DataFrame(columns=colonnes)
    d = derive.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["couverture"] = d["n_px"] / d.groupby(["classe", "mois"])["n_px"].transform("max")
    d = d[d["couverture"] >= couverture_min]
    lignes: list[dict[str, object]] = []
    for classe, jeu in d.groupby("classe"):
        jeu = jeu.sort_values("date").reset_index(drop=True)
        jours = jeu["date"].to_numpy().astype("datetime64[D]").astype(int)
        for i, (_, ligne) in enumerate(jeu.iterrows()):
            voisins = (np.abs(jours - jours[i]) <= fenetre_jours) & (np.arange(len(jeu)) != i)
            if voisins.sum() < 2:
                continue
            lignes.append(
                {
                    "classe": classe,
                    "date": ligne["date"],
                    "annee": int(ligne["date"].year),
                    "plateformes": ligne["plateformes"],
                    "offset": ligne["offset"],
                    "residu_ndvi": float(ligne["ndvi"] - jeu.loc[voisins, "ndvi"].median()),
                    "residu_ndmi": float(ligne["ndmi"] - jeu.loc[voisins, "ndmi"].median()),
                }
            )
    return pd.DataFrame(lignes, columns=colonnes)


def groupes(res: pd.DataFrame, plans_min: int) -> pd.DataFrame:
    """Résidu médian de chaque plateforme (par classe et par année) et de chaque offset (par classe,
    sur toute la période : les deux offsets se mêlent rarement dans une même année).

    Les plans mêlant deux plateformes ne comptent pas pour le critère « plateforme »."""
    colonnes = ["classe", "periode", "critere", "groupe", "n_plans", "residu_ndvi", "residu_ndmi"]
    if res.empty:
        return pd.DataFrame(columns=colonnes)
    r = res.assign(
        offset=res["offset"].map(lambda o: f"offset {o:g}"),
        periode=res["annee"].astype(str),
        toutes=f"{res['annee'].min()}-{res['annee'].max()}",
    )
    lignes: list[pd.DataFrame] = []
    for critere, colonne, periode, jeu in (
        ("plateforme", "plateformes", "periode", r[~r["plateformes"].str.contains(",")]),
        ("offset", "offset", "toutes", r),
    ):
        agr = (
            jeu.groupby(["classe", periode, colonne])
            .agg(
                n_plans=("residu_ndvi", "size"),
                residu_ndvi=("residu_ndvi", "median"),
                residu_ndmi=("residu_ndmi", "median"),
            )
            .reset_index()
            .rename(columns={colonne: "groupe", periode: "periode"})
            .assign(critere=critere)
        )
        lignes.append(agr[agr["n_plans"] >= plans_min])
    return pd.concat(lignes, ignore_index=True)[colonnes]


def ecarts(grp: pd.DataFrame, seuil: float) -> pd.DataFrame:
    """Écart, par classe, période et critère, entre le groupe au résidu le plus haut et le plus bas
    (au moins deux groupes) ; `anormal` au-delà de `seuil` en NDVI ou en NDMI."""
    colonnes = [
        "classe",
        "periode",
        "critere",
        "groupes",
        "n_plans",
        "ecart_ndvi",
        "ecart_ndmi",
        "anormal",
    ]
    lignes: list[dict[str, object]] = []
    for (classe, periode, critere), jeu in grp.groupby(["classe", "periode", "critere"]):
        if len(jeu) < 2:
            continue
        ecart_ndvi = float(jeu["residu_ndvi"].max() - jeu["residu_ndvi"].min())
        ecart_ndmi = float(jeu["residu_ndmi"].max() - jeu["residu_ndmi"].min())
        lignes.append(
            {
                "classe": classe,
                "periode": periode,
                "critere": critere,
                "groupes": ",".join(sorted(jeu["groupe"])),
                "n_plans": int(jeu["n_plans"].sum()),
                "ecart_ndvi": ecart_ndvi,
                "ecart_ndmi": ecart_ndmi,
                "anormal": bool(max(ecart_ndvi, ecart_ndmi) > seuil),
            }
        )
    return pd.DataFrame(lignes, columns=colonnes)


def calculer(config: Config) -> dict[str, pd.DataFrame]:
    rapport, plans, derive = _lire(config)
    comp = config.projet.satellite.composites
    grp = groupes(
        residus(derive, comp.derive_fenetre_jours, comp.derive_couverture_min),
        comp.derive_plans_min,
    )
    tables = {
        "composites_rapport": rapport.sort_values(["annee", "mois"], ignore_index=True),
        "composites_plans": plans.sort_values(["mois", "cle"], ignore_index=True),
        "derive_cibles": derive.sort_values(["mois", "classe", "cle"], ignore_index=True),
        "derive_groupes": grp,
        "derive_ecarts": ecarts(grp, comp.seuil_derive),
    }
    sortie: Path = dossier_satellite(config)
    sortie.mkdir(parents=True, exist_ok=True)
    for nom, table in tables.items():
        table.to_parquet(sortie / f"{nom}.parquet", index=False)
    return tables


def resume(tables: dict[str, pd.DataFrame]) -> str:
    """Quelques chiffres pour le journal : mois, scènes écartées, écarts anormaux."""
    rapport, ecart = tables["composites_rapport"], tables["derive_ecarts"]
    lignes = [
        f"{len(rapport)} mois, {int(rapport['scenes_retenues'].sum())} scènes retenues, "
        f"{int(rapport['scenes_baseline_inconnue'].sum())} sans baseline, "
        f"{int(rapport['scenes_doublons_ecartes'].sum())} doublons écartés"
    ]
    for critere, jeu in ecart.groupby("critere"):
        lignes.append(
            f"écarts {critere} : {len(jeu)} classes-périodes comparées, "
            f"{int(jeu['anormal'].sum())} "
            f"anormales, plus grand écart NDVI {jeu['ecart_ndvi'].max():.3f}, "
            f"NDMI {jeu['ecart_ndmi'].max():.3f}"
        )
    return "\n".join(lignes)
