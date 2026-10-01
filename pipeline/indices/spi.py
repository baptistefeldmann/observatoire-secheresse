"""SPI de la semaine par zone (SPEC §6.2, méthodologie D7).

Cumul de pluie de la zone sur 30, 91 et 182 jours terminés le dimanche, converti par
Φ⁻¹(q0 + (1 − q0) Fγ(x)) avec les paramètres de la normale de la même semaine."""

from __future__ import annotations

import pandas as pd
from scipy import stats

from pipeline.config import Config
from pipeline.indices.commun import detail_json, libelle_semaine, z_probabilite
from pipeline.reference.commun import semaine_ref
from pipeline.reference.spi import cumuls_dimanches

COLONNES = ["zone_id", "semaine", "indice", "valeur", "n_stations", "detail"]


def calculer(
    config: Config, pluie: pd.DataFrame, normales: pd.DataFrame, dimanches: pd.DatetimeIndex
) -> pd.DataFrame:
    """Une ligne par zone, fenêtre SPI et semaine ; `pluie` : tableau date x zone_id (mm)."""
    morceaux = []
    for indice, jours in config.projet.indices.spi.fenetres_jours.items():
        cumuls = cumuls_dimanches(pluie, jours)
        cumuls = cumuls[cumuls["date"].isin(dimanches)].assign(indice=indice)
        cumuls["semaine_ref"] = semaine_ref(cumuls["date"])
        morceaux.append(
            cumuls.merge(
                normales,
                left_on=["zone_id", "indice", "semaine_ref"],
                right_on=["zone_id", "indice", "semaine"],
            )
        )
    table = pd.concat(morceaux, ignore_index=True) if morceaux else pd.DataFrame()
    if table.empty:
        return pd.DataFrame(columns=COLONNES)
    gamma = stats.gamma.cdf(table["cumul"], table["forme"], scale=table["echelle"])
    table["valeur"] = z_probabilite(table["q0"] + (1 - table["q0"]) * gamma)
    table["semaine"] = [libelle_semaine(d.date()) for d in table["date"]]
    table["n_stations"] = pd.NA
    table["detail"] = [
        detail_json({"periode_ref": p, "hors_reference": bool(h)})
        for p, h in zip(table["periode_ref"], table["hors_reference"], strict=True)
    ]
    return table[COLONNES]
