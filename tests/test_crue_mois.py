"""Médiane mensuelle et tendance d'hiver de la surface de crue (V2.2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipeline.config import Config
from pipeline.indices import crue as agregats
from pipeline.raster import crue as raster_crue


def _passages(lignes: list[tuple[str, str, str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"marais": m, "date": d, "variante": v, "surface_ha": s, "pct_valides": p, "orbite": 81}
            for m, d, v, s, p in lignes
        ]
    )


def test_mediane_mensuelle() -> None:
    p = _passages(
        [
            ("m", "2024-01-05", "fixe", 100.0, 100.0),
            ("m", "2024-01-17", "fixe", 300.0, 100.0),
            ("m", "2024-01-29", "fixe", 200.0, 100.0),
            ("m", "2024-02-03", "fixe", 50.0, 100.0),
            ("m", "2024-01-05", "hydro", 10.0, 100.0),
        ]
    )
    mois = agregats.agreger_mois(p).set_index(["variante", "mois"])
    assert mois.loc[("fixe", "2024-01"), "surface_ha"] == 200.0
    assert mois.loc[("fixe", "2024-01"), "n_passages"] == 3
    assert mois.loc[("fixe", "2024-02"), "surface_ha"] == 50.0
    assert mois.loc[("hydro", "2024-01"), "surface_ha"] == 10.0


def test_passage_peu_observable_ecarte() -> None:
    p = _passages(
        [
            ("m", "2024-01-05", "fixe", 100.0, 100.0),
            ("m", "2024-01-17", "fixe", 900.0, 30.0),  # 30 % du domaine observable : écarté
            ("m", "2024-01-29", "fixe", float("nan"), float("nan")),  # sans référence : écarté
        ]
    )
    sans_seuil = agregats.agreger_mois(p).iloc[0]
    assert sans_seuil["n_passages"] == 2
    avec = agregats.agreger_mois(p, pct_valides_min=50).iloc[0]
    assert avec["n_passages"] == 1
    assert avec["surface_ha"] == 100.0


def test_regimes_agreges() -> None:
    p = _passages(
        [("m", "2024-01-05", "fixe", 100.0, 100.0), ("m", "2024-01-17", "fixe", 200.0, 100.0)]
    )
    p["ha_mouille"] = [40.0, 80.0]
    mois = agregats.agreger_mois(p).iloc[0]
    assert mois["ha_mouille"] == 60.0


def _hivers(pente: float, debut: int = 2016, n: int = 10) -> pd.DataFrame:
    lignes = []
    for k in range(n):
        for jour in ("12-05", "01-10", "02-12", "03-08"):
            annee = debut + k if jour == "12-05" else debut + k + 1
            lignes.append(("m", f"{annee}-{jour}", "fixe", 1000 + pente * k, 100.0))
    return _passages(lignes)


def test_tendance_croissante() -> None:
    t = agregats.tendance_hiver(_hivers(pente=25.0)).iloc[0]
    assert t["n_hivers"] == 10
    assert (t["premier_hiver"], t["dernier_hiver"]) == (2016, 2025)
    assert t["pente_ha_par_an"] == pytest.approx(25.0)
    assert t["tau_kendall"] == pytest.approx(1.0)
    assert t["p_kendall"] < 0.001


def test_tendance_nulle() -> None:
    p = _hivers(pente=0.0)
    p.loc[p["date"].str.startswith("2018"), "surface_ha"] += (
        300  # un hiver exceptionnel, sans tendance
    )
    t = agregats.tendance_hiver(p).iloc[0]
    assert abs(t["pente_ha_par_an"]) < 5
    assert t["p_kendall"] > 0.1


def test_hiver_incomplet_ou_trop_court() -> None:
    p = _hivers(pente=10.0, n=3)
    t = agregats.tendance_hiver(p).iloc[0]
    assert t["n_hivers"] == 3
    assert "pente_ha_par_an" not in t or pd.isna(t.get("pente_ha_par_an"))  # moins de 5 hivers
    # un hiver avec moins de trois passages n'est pas compté
    seul = _passages(
        [("m", "2020-01-10", "fixe", 100.0, 100.0), ("m", "2020-02-10", "fixe", 100.0, 100.0)]
    )
    assert agregats.tendance_hiver(seul).empty


def test_l_ete_n_entre_pas_dans_l_hiver() -> None:
    lignes = [("m", f"{a}-07-15", "fixe", 5.0, 100.0) for a in range(2016, 2026)]
    assert agregats.tendance_hiver(_passages(lignes)).empty


def test_hiver_sans_decembre_ecarte() -> None:
    """D16 : le premier hiver de la série (début au 3 janvier) n'entre pas dans la tendance."""
    p = _hivers(pente=0.0, debut=2015, n=6)
    p = p[~p["date"].str.startswith("2015-12")]  # pas de passage en décembre 2015
    t = agregats.tendance_hiver(p).iloc[0]
    assert t["n_hivers"] == 5
    assert t["premier_hiver"] == 2016


def test_seule_la_reference_retenue_est_publiee(config: Config, tmp_path: Path) -> None:
    chemins = config.projet.chemins.model_copy(update={"rasters": tmp_path / "rasters"})
    config = config.model_copy(
        update={"projet": config.projet.model_copy(update={"chemins": chemins})}
    )
    p = _passages(
        [
            ("m", "2024-01-05", "fixe", 100.0, 100.0),
            ("m", "2024-01-05", "hydro", 10.0, 100.0),
        ]
    )
    chemin = raster_crue.fichier_passages(config)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    p.to_parquet(chemin, index=False)
    tables = agregats.calculer(config)
    assert set(tables["crue_mois"]["variante"]) == {"fixe"}
    assert (chemin.parent / "crue_mois.parquet").is_file()
