"""Normales de référence sur des données synthétiques (résultats connus d'avance)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pipeline import ingestion, reference, referentiels
from pipeline.config import Config, Periode, Rupture
from pipeline.http import ClientHttp
from pipeline.reference import commun, debit, ips, spi
from pipeline.reference import ruptures as detection

REF = Periode(debut=1991, fin=2020, annees_min=15)


def _journalier(station_id: str, debut: str, fin: str, colonne: str, valeur: float) -> pd.DataFrame:
    dates = pd.date_range(debut, fin, freq="D")
    return pd.DataFrame({"station_id": station_id, "date": dates.date, colonne: valeur})


@pytest.mark.parametrize(
    ("valides", "annees", "periode", "hors"),
    [
        (set(range(1991, 2011)), list(range(1991, 2011)), "1991-2020", False),
        (set(range(2011, 2027)), list(range(2011, 2027)), "2011-2026", True),  # 10 ans dans la réf.
        (set(range(2015, 2027)), [], "", True),  # 12 ans en tout : pas de normale
    ],
)
def test_choix_des_annees(valides: set[int], annees: list[int], periode: str, hors: bool) -> None:
    choix = commun.choisir_annees(valides, REF)
    assert (choix.annees, choix.periode_ref, choix.hors_reference) == (annees, periode, hors)


def test_ajustement_gamma_retrouve_les_parametres() -> None:
    echantillon = np.random.default_rng(0).gamma(shape=3.0, scale=20.0, size=20_000)
    forme, echelle, q0 = spi.ajuster_gamma(echantillon)
    assert forme == pytest.approx(3.0, rel=0.03)
    assert echelle == pytest.approx(20.0, rel=0.03)
    assert q0 == 0


def test_cumuls_aux_dimanches() -> None:
    dates = pd.date_range("2026-01-01", "2026-04-30", freq="D")
    pluie = pd.DataFrame({"Z1": 1.0, "Z2": 2.0}, index=dates)
    cumuls = spi.cumuls_dimanches(pluie, 30)
    assert (pd.DatetimeIndex(cumuls["date"]).dayofweek == 6).all()
    assert cumuls["date"].min() >= pd.Timestamp("2026-01-30")  # fenêtre complète seulement
    assert set(cumuls.loc[cumuls["zone_id"] == "Z1", "cumul"]) == {30.0}
    assert set(cumuls.loc[cumuls["zone_id"] == "Z2", "cumul"]) == {60.0}


def test_mois_incomplet_ecarte_de_l_ips() -> None:
    obs = _journalier("piezo:A", "2026-01-01", "2026-02-09", "niveau_ngf", 5.0)
    mensuel = ips.moyennes_mensuelles(obs, jours_min=10)
    assert list(mensuel["mois"]) == [1]  # février n'a que 9 jours


def test_normales_ips_avec_et_sans_reference(config: Config) -> None:
    obs = pd.concat(
        [
            _journalier("piezo:A", "1991-01-01", "2010-12-31", "niveau_ngf", 5.0),
            _journalier("piezo:B", "2011-01-01", "2026-12-31", "niveau_ngf", 3.0),
        ]
    )
    normales = ips.normales(config, obs)
    assert len(normales) == 24

    def septembre(station_id: str) -> dict[str, object]:
        ligne = normales[(normales["station_id"] == station_id) & (normales["mois"] == 9)]
        return dict(ligne.iloc[0])

    a, b = septembre("piezo:A"), septembre("piezo:B")
    assert (a["n_annees"], a["periode_ref"], a["hors_reference"]) == (20, "1991-2020", False)
    assert (b["n_annees"], b["periode_ref"], b["hors_reference"]) == (16, "2011-2026", True)
    assert list(a["valeurs_ref"]) == [5.0] * 20  # type: ignore[call-overload]


def test_raccordement_des_stations(config: Config) -> None:
    # Tiffauges (stations.yaml) : M711241020 prioritaire, M711241010 comble les manques
    obs = pd.concat(
        [
            _journalier("hydro:M711241010", "2020-01-01", "2020-01-10", "qmj_ls", 100.0),
            _journalier("hydro:M711241020", "2020-01-06", "2020-01-15", "qmj_ls", 200.0),
        ]
    )
    serie = debit.series(config, obs)
    assert set(serie["station_id"]) == {"hydro:M711241020"}
    assert len(serie) == 15
    valeurs = serie.set_index("date")["qmj_ls"]
    assert valeurs[date(2020, 1, 5)] == 100.0 and valeurs[date(2020, 1, 6)] == 200.0


def test_q7_exige_assez_de_jours() -> None:
    obs = _journalier("hydro:X", "2026-01-01", "2026-01-14", "qmj_ls", 10.0)
    obs = obs[~obs["date"].isin([date(2026, 1, d) for d in (9, 10, 11)])]  # 3 jours manquants
    q7 = debit.q7(obs, jours_min=5).set_index("date")["q7"]
    assert pd.Timestamp("2026-01-08") in q7.index  # 7 jours renseignés
    assert pd.Timestamp("2026-01-10") in q7.index  # 4 au 10 : 5 jours sur 7
    assert pd.Timestamp("2026-01-14") not in q7.index  # 8 au 14 : 4 jours sur 7


def test_normales_debit(config: Config) -> None:
    obs = _journalier("hydro:X", "1991-01-01", "2010-12-31", "qmj_ls", 50.0)
    normales = debit.normales(config, obs)
    assert list(normales["semaine"]) == list(range(1, 53))
    # la fenêtre de la semaine 52 de 2010 déborde sur janvier 2011, hors des données
    assert (normales["n_annees"].iloc[:-1] == 20).all() and normales["n_annees"].iloc[-1] == 19
    assert not normales["hors_reference"].any()
    # ±15 jours autour du dimanche : jusqu'à 31 valeurs par année
    assert normales["valeurs_ref"].map(len).max() == 31 * 20


def test_pas_assez_d_annees_tables_vides(config: Config, client: ClientHttp) -> None:
    # fixtures : quelques jours de septembre 2026 seulement -> aucune normale, mais pas d'erreur
    referentiels.construire(config, client, date(2026, 9, 30))
    ingestion.ingerer(config, client, date(2026, 9, 30), date(2026, 9, 1))
    chemins = reference.calculer(config)
    for chemin in chemins.values():
        table = pd.read_parquet(chemin)
        assert table.empty and "n_annees" in table.columns


def _avec_ruptures(config: Config, *ruptures: tuple[str, int]) -> Config:
    liste = [Rupture(station=s, annee=a, motif="test") for s, a in ruptures]
    return config.model_copy(
        update={"stations": config.stations.model_copy(update={"ruptures": liste})}
    )


def test_pettitt_detecte_un_saut() -> None:
    bruit = np.random.default_rng(1).normal(0, 0.1, 30)
    indice, p = detection.pettitt(bruit + np.r_[np.zeros(18), np.ones(12)])
    assert indice == 18 and p < 0.001
    _, p_stationnaire = detection.pettitt(bruit)
    assert p_stationnaire > 0.05


def test_reference_apres_rupture() -> None:
    ref = Periode(debut=1991, fin=2020, annees_min=15, annees_min_apres_rupture=8)
    valides = set(range(1991, 2026))
    choix = commun.choisir_annees(valides, ref, rupture=2011)
    assert (choix.annees, choix.periode_ref, choix.hors_reference) == (
        list(range(2011, 2026)),
        "2011-2025",
        True,
    )
    assert commun.choisir_annees(valides, ref, rupture=2018).annees == list(range(2018, 2026))
    assert commun.choisir_annees(valides, ref, rupture=2021).annees == []  # 5 ans < 8


def test_normales_ips_limitees_apres_la_rupture(config: Config) -> None:
    obs = pd.concat(
        [
            _journalier("piezo:A", "1991-01-01", "2010-12-31", "niveau_ngf", 1.0),
            _journalier("piezo:A", "2011-01-01", "2025-12-31", "niveau_ngf", 2.0),  # saut
        ]
    )
    normales = ips.normales(_avec_ruptures(config, ("piezo:A", 2011)), obs)
    assert (normales["periode_ref"] == "2011-2025").all() and normales["hors_reference"].all()
    assert (normales["rupture"] == 2011).all()
    assert set(normales["valeurs_ref"].iloc[0]) == {2.0}  # l'ancien régime est écarté


def test_detection_signale_les_ruptures(config: Config) -> None:
    brut = config.projet.chemins.data / "raw"
    (brut / "piezo").mkdir(parents=True)
    (brut / "hydro").mkdir(parents=True)
    obs = pd.concat(
        [
            _journalier("piezo:SAUT", "1991-01-01", "2010-12-31", "niveau_ngf", 1.0),
            _journalier("piezo:SAUT", "2011-01-01", "2025-12-31", "niveau_ngf", 2.0),
            _journalier("piezo:STABLE", "1991-01-01", "2025-12-31", "niveau_ngf", 1.0),
        ]
    )
    obs["niveau_ngf"] += np.random.default_rng(2).normal(0, 0.05, len(obs))
    obs.to_parquet(brut / "piezo" / "chroniques_2000.parquet")
    _journalier("hydro:Q", "2000-01-01", "2000-12-31", "qmj_ls", 1.0).to_parquet(
        brut / "hydro" / "qmj_2000.parquet"
    )
    table = detection.detecter(_avec_ruptures(config, ("piezo:SAUT", 2011))).set_index("station_id")
    assert table.loc["piezo:SAUT", "annee_rupture"] == 2011
    assert bool(table.loc["piezo:SAUT", "significative"]) and bool(
        table.loc["piezo:SAUT", "traitee"]
    )
    assert not bool(table.loc["piezo:STABLE", "significative"])
