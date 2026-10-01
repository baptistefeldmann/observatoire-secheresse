"""Normales du SPI par zone (SPEC §6.2, méthodologie D7).

Pluie de la zone = moyenne des mailles SIM pondérée par leur surface dans la zone (option A :
standardiser après agrégation, pour que le SPI de zone reste sur l'échelle des 7 classes).
Pour chaque zone, fenêtre (30, 91, 182 jours) et semaine ISO : loi gamma ajustée sur les cumuls
terminés le dimanche de cette semaine, sur les années de référence.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats

from pipeline.config import Config
from pipeline.reference.commun import choisir_annees, lire_brut, semaine_ref


def poids_mailles(config: Config) -> pd.DataFrame:
    """Part de chaque maille dans chaque zone (somme à 1 par zone)."""
    dossier = config.projet.chemins.data / "referentiels"
    zones = gpd.read_parquet(dossier / "zones.parquet")[["zone_id", "geometry"]]
    mailles = gpd.read_parquet(dossier / "mailles_safran.parquet")
    inter = gpd.overlay(mailles, zones, how="intersection", keep_geom_type=True)
    inter["surface"] = inter.area
    poids = inter.groupby(["zone_id", "maille_id"], as_index=False)["surface"].sum()
    poids["poids"] = poids["surface"] / poids.groupby("zone_id")["surface"].transform("sum")
    resultat: pd.DataFrame = poids[["zone_id", "maille_id", "poids"]]
    return resultat


def pluie_zones(config: Config, meteo: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pluie journalière par zone : tableau date x zone_id (mm)."""
    meteo = meteo if meteo is not None else lire_brut(config, "meteo", "sim")
    jointure = meteo[["maille_id", "date", "precip_mm"]].merge(
        poids_mailles(config), on="maille_id"
    )
    jointure["contribution"] = jointure["precip_mm"] * jointure["poids"]
    pluie = jointure.pivot_table(
        index="date", columns="zone_id", values="contribution", aggfunc="sum"
    )
    pluie.index = pd.to_datetime(pluie.index)
    return pluie.sort_index()


def cumuls_dimanches(pluie: pd.DataFrame, jours: int) -> pd.DataFrame:
    """Cumul glissant de `jours` jours, aux dimanches : colonnes zone_id, date, cumul."""
    journalier = pluie.asfreq("D")
    cumul = journalier.rolling(jours, min_periods=jours).sum()
    dimanches = cumul[pd.DatetimeIndex(cumul.index).dayofweek == 6]
    long = dimanches.reset_index(names="date").melt(
        id_vars="date", var_name="zone_id", value_name="cumul"
    )
    return long.dropna(subset=["cumul"])


def ajuster_gamma(cumuls: np.ndarray) -> tuple[float, float, float]:
    """(forme, échelle, q0) : loi gamma sur les cumuls positifs, q0 = part de cumuls nuls."""
    positifs = cumuls[cumuls > 0]
    q0 = 1 - len(positifs) / len(cumuls)
    forme, _, echelle = stats.gamma.fit(positifs, floc=0)
    return float(forme), float(echelle), float(q0)


COLONNES = [
    "zone_id",
    "indice",
    "semaine",
    "forme",
    "echelle",
    "q0",
    "n_annees",
    "periode_ref",
    "hors_reference",
]


def normales(config: Config, pluie: pd.DataFrame | None = None) -> pd.DataFrame:
    ref = config.projet.periode_reference.hydro_meteo
    pluie = pluie if pluie is not None else pluie_zones(config)
    lignes = []
    for indice, jours in config.projet.indices.spi.fenetres_jours.items():
        cumuls = cumuls_dimanches(pluie, jours)
        cumuls["annee"] = cumuls["date"].dt.isocalendar().year.astype("int64")
        cumuls["semaine"] = semaine_ref(cumuls["date"])
        for (zone_id, semaine), groupe in cumuls.groupby(["zone_id", "semaine"]):
            choix = choisir_annees(set(groupe["annee"]), ref)
            if not choix.annees:
                continue
            echantillon = groupe.loc[groupe["annee"].isin(choix.annees), "cumul"].to_numpy()
            forme, echelle, q0 = ajuster_gamma(echantillon)
            lignes.append(
                {
                    "zone_id": zone_id,
                    "indice": indice,
                    "semaine": semaine,
                    "forme": forme,
                    "echelle": echelle,
                    "q0": q0,
                    "n_annees": len(choix.annees),
                    "periode_ref": choix.periode_ref,
                    "hors_reference": choix.hors_reference,
                }
            )
    table = pd.DataFrame(lignes, columns=COLONNES)
    return table.sort_values(["zone_id", "indice", "semaine"], ignore_index=True)
