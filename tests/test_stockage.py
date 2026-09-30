from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from pipeline import stockage

CLES = ["station_id", "date"]
VALEURS = ["volume_m3"]


def _obs(volumes: dict[date, float], ingere_le: date) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": pd.Series(["retenue:A"] * len(volumes), dtype="string"),
            "date": list(volumes),
            "volume_m3": list(volumes.values()),
            "ingere_le": ingere_le,
        }
    )


def test_un_fichier_par_annee(tmp_path: Path) -> None:
    obs = _obs({date(2025, 12, 28): 1.0, date(2026, 1, 4): 2.0}, date(2026, 1, 5))
    chemins = stockage.fusionner_par_annee(obs, tmp_path, "retenues", CLES, VALEURS)
    assert [c.name for c in chemins] == ["retenues_2025.parquet", "retenues_2026.parquet"]


def test_idempotent(tmp_path: Path) -> None:
    obs = _obs({date(2026, 1, 4): 2.0, date(2026, 1, 11): 3.0}, date(2026, 1, 12))
    [chemin] = stockage.fusionner_par_annee(obs, tmp_path, "r", CLES, VALEURS)
    avant = chemin.read_bytes()
    stockage.fusionner_par_annee(obs, tmp_path, "r", CLES, VALEURS)
    assert chemin.read_bytes() == avant


def test_releve_inchange_garde_sa_date_d_ingestion(tmp_path: Path) -> None:
    stockage.fusionner_par_annee(
        _obs({date(2026, 1, 4): 2.0}, date(2026, 1, 5)), tmp_path, "r", CLES, VALEURS
    )
    [chemin] = stockage.fusionner_par_annee(
        _obs({date(2026, 1, 4): 2.0, date(2026, 1, 11): 3.0}, date(2026, 1, 12)),
        tmp_path, "r", CLES, VALEURS,
    )  # fmt: skip
    table = pd.read_parquet(chemin)
    assert dict(zip(table["date"], table["ingere_le"], strict=True)) == {
        date(2026, 1, 4): date(2026, 1, 5),
        date(2026, 1, 11): date(2026, 1, 12),
    }


def test_releve_corrige_remplace_l_ancien(tmp_path: Path) -> None:
    stockage.fusionner_par_annee(
        _obs({date(2026, 1, 4): 2.0}, date(2026, 1, 5)), tmp_path, "r", CLES, VALEURS
    )
    [chemin] = stockage.fusionner_par_annee(
        _obs({date(2026, 1, 4): 2.5}, date(2026, 1, 12)), tmp_path, "r", CLES, VALEURS
    )
    table = pd.read_parquet(chemin)
    assert len(table) == 1
    assert table.loc[0, "volume_m3"] == 2.5
    assert table.loc[0, "ingere_le"] == date(2026, 1, 12)


def test_valeur_manquante_completee_a_la_source(tmp_path: Path) -> None:
    def obs(qualification: str | None, ingere_le: date) -> pd.DataFrame:
        table = _obs({date(2026, 1, 4): 2.0}, ingere_le)
        table["qualification"] = pd.Series([qualification], dtype="string")
        return table

    valeurs = ["volume_m3", "qualification"]
    stockage.fusionner_par_annee(obs(None, date(2026, 1, 5)), tmp_path, "r", CLES, valeurs)
    [chemin] = stockage.fusionner_par_annee(
        obs("validée", date(2026, 1, 12)), tmp_path, "r", CLES, valeurs
    )
    table = pd.read_parquet(chemin)
    assert table.loc[0, "qualification"] == "validée"
    assert table.loc[0, "ingere_le"] == date(2026, 1, 12)
