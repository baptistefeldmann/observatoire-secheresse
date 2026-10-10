"""Indices hebdomadaires sur des données synthétiques (résultats connus d'avance)."""

from __future__ import annotations

import json
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from scipy import stats
from shapely.geometry import Point, box

from pipeline import indices, reference
from pipeline.config import Config, Zonage, Zone
from pipeline.indices import commun, composite, debit, ips, onde, rang, spi

ZONE = Zone(
    zone_id="Z",
    libelle="Zone de test",
    type_zone="hydrogeol",
    masses_eau=["FRGG000"],
    ponderations={"spi_3": 0.4, "ips": 0.3, "debit": 0.3},
)


@pytest.fixture
def config_z(config: Config) -> Config:
    """Une zone pondérée sur les trois composantes, sans rupture ni raccordement."""
    stations = config.stations.model_copy(update={"ruptures": [], "raccordements_hydro": []})
    zonage = Zonage(fragment_max_km2=20, zones=[ZONE])
    return config.model_copy(update={"zonage": zonage, "stations": stations})


def _dimanches(*jours: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(jours)))


def _journalier(station_id: str, debut: str, fin: str, colonne: str, valeur: float) -> pd.DataFrame:
    dates = pd.date_range(debut, fin, freq="D")
    return pd.DataFrame({"station_id": station_id, "date": dates.date, colonne: valeur})


# --- Outils communs ------------------------------------------------------------------------


def test_semaines_iso() -> None:
    assert commun.libelle_semaine(date(2026, 9, 27)) == "2026-W39"
    assert commun.dimanche("2026-W39") == date(2026, 9, 27)
    assert commun.dimanche("2020-W53") == date(2021, 1, 3)  # année ISO à 53 semaines
    assert commun.derniere_semaine_complete(date(2026, 10, 1)) == "2026-W39"  # jeudi
    assert commun.derniere_semaine_complete(date(2026, 10, 4)) == "2026-W39"  # dimanche
    assert commun.derniere_semaine_complete(date(2026, 10, 5)) == "2026-W40"  # lundi
    assert len(commun.dimanches("2020-W52", "2021-W02")) == 4


def test_valeur_standardisee_par_le_rang() -> None:
    reference = np.array([4.0, 5.0, 6.0, 7.0, 8.0])
    assert commun.z_rang(6.0, reference) == pytest.approx(0.0)  # médiane
    assert commun.z_rang(4.5, reference) == pytest.approx(-commun.z_rang(7.5, reference))
    # au-delà de toute la référence : extrême mais fini, (n + 1 − 0,44) / (n + 1,12)
    assert commun.z_rang(100.0, reference) == pytest.approx(stats.norm.ppf(5.56 / 6.12))
    assert commun.z_rang(100.0, reference) == commun.z_rang(9.0, reference)


def test_classes_aux_seuils(config: Config) -> None:
    valeurs = pd.Series([-1.28, -1.27, -0.25, 0.0, 0.25, 1.28, 1.29, np.nan])
    classes = commun.classer(valeurs, config.classes)
    assert classes.tolist()[:7] == [1, 2, 3, 4, 4, 6, 7]
    assert pd.isna(classes.iloc[7])


# --- Indices par variable ------------------------------------------------------------------


def test_spi_de_la_semaine(config_z: Config) -> None:
    dates = pd.date_range("2025-01-01", "2026-03-01", freq="D")
    pluie = pd.DataFrame({"Z": 1.0, "SEC": 0.0}, index=dates)
    dimanche = pd.Timestamp("2026-02-01")  # semaine 5
    median = 30 / stats.gamma.ppf(0.5, 2.0)  # échelle telle que la médiane vaille 30 mm
    normales = pd.DataFrame(
        {
            "zone_id": ["Z", "SEC", "Z"],
            "indice": ["spi_1", "spi_1", "spi_6"],
            "semaine": [5, 5, 5],
            "forme": 2.0,
            "echelle": median,
            "q0": [0.0, 0.2, 0.0],
            "n_annees": 30,
            "periode_ref": "1991-2020",
            "hors_reference": False,
        }
    )
    table = spi.calculer(config_z, pluie, normales, _dimanches("2026-02-01"))
    valeurs = table.set_index(["zone_id", "indice"])["valeur"]
    assert valeurs[("Z", "spi_1")] == pytest.approx(0.0, abs=1e-9)  # 30 mm = médiane
    assert valeurs[("SEC", "spi_1")] == pytest.approx(stats.norm.ppf(0.2))  # Φ⁻¹(q0)
    assert ("Z", "spi_3") not in valeurs.index  # pas de normale : pas d'indice
    assert set(table["semaine"]) == {commun.libelle_semaine(dimanche.date())}


def test_spi_borne_sans_cumul_nul_dans_la_reference(config_z: Config) -> None:
    pluie = pd.DataFrame({"Z": 0.0}, index=pd.date_range("2026-01-01", "2026-02-28"))
    normales = pd.DataFrame(
        {"zone_id": ["Z"], "indice": ["spi_1"], "semaine": [5], "forme": 2.0, "echelle": 10.0,
         "q0": 0.0, "n_annees": 30, "periode_ref": "1991-2020", "hors_reference": False}
    )  # fmt: skip
    table = spi.calculer(config_z, pluie, normales, _dimanches("2026-02-01"))
    assert table["valeur"].tolist() == [-commun.Z_MAX]


def _normales_ips(station_id: str, rupture: int | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": station_id,
            "mois": range(1, 13),
            "valeurs_ref": [[4.0, 5.0, 6.0, 7.0, 8.0]] * 12,
            "n_annees": 5,
            "periode_ref": "1991-2020",
            "hors_reference": False,
            "rupture": pd.array([rupture] * 12, dtype="Int64"),
        }
    )


def test_ips_mois_en_cours_ou_precedent(config_z: Config) -> None:
    obs = pd.concat(
        [
            _journalier("piezo:A", "2026-01-01", "2026-01-31", "niveau_ngf", 5.0),
            _journalier("piezo:A", "2026-02-01", "2026-02-28", "niveau_ngf", 6.0),
            _journalier("piezo:A", "2026-03-01", "2026-03-08", "niveau_ngf", 8.0),
        ]
    )
    dimanches = _dimanches("2026-02-15", "2026-03-08", "2026-04-19", "2027-03-07")
    table = ips.calculer(config_z, obs, _normales_ips("piezo:A"), dimanches)
    lignes = table.set_index("semaine")
    # 15 jours de février au 15 : mois en cours, niveau 6 = médiane de la référence
    assert lignes.loc["2026-W07", "valeur"] == pytest.approx(0.0)
    assert lignes.loc["2026-W07", "date_mesure"] == date(2026, 2, 15)
    # 8 jours de mars seulement : février, complet, est retenu
    assert lignes.loc["2026-W10", "valeur"] == pytest.approx(0.0)
    assert lignes.loc["2026-W10", "date_mesure"] == date(2026, 2, 28)
    assert bool(lignes.loc["2026-W10", "dans_composite"])
    # 50 jours sans mesure retenue : affiché, mais hors composite (D1)
    assert not bool(lignes.loc["2026-W16", "dans_composite"])
    # plus d'un an : station hors service, pas d'indice
    assert "2027-W09" not in lignes.index


def test_ips_absent_avant_la_rupture(config_z: Config) -> None:
    obs = _journalier("piezo:A", "2010-01-01", "2012-12-31", "niveau_ngf", 6.0)
    table = ips.calculer(
        config_z, obs, _normales_ips("piezo:A", rupture=2011),
        _dimanches("2010-06-13", "2011-06-12"),
    )  # fmt: skip
    assert table["semaine"].tolist() == ["2011-W23"]


def test_indice_de_debit_du_dimanche(config_z: Config) -> None:
    obs = _journalier("hydro:Q", "2026-01-01", "2026-01-25", "qmj_ls", 10.0)
    normales = pd.DataFrame(
        {"station_id": ["hydro:Q"], "semaine": [3], "valeurs_ref": [[5.0, 10.0, 15.0]],
         "n_annees": 30, "periode_ref": "1991-2020", "hors_reference": False,
         "rupture": pd.array([None], dtype="Int64")}
    )  # fmt: skip
    table = debit.calculer(config_z, obs, normales, _dimanches("2026-01-18", "2026-02-01"))
    assert table["semaine"].tolist() == ["2026-W03"]  # pas de Q7 au 1er février
    assert table["valeur"].iloc[0] == pytest.approx(0.0)
    assert table["date_mesure"].iloc[0] == date(2026, 1, 18)


def test_part_de_stations_onde_sans_ecoulement() -> None:
    stations = pd.DataFrame({"station_id": ["onde:1", "onde:2"], "zone_id": ["Z", "Z"]})
    obs = pd.DataFrame(
        {
            "station_id": ["onde:1", "onde:2"] * 3,
            "date_campagne": [date(2026, 7, 20)] * 2 + [date(2026, 7, 24)] * 2
            + [date(2026, 8, 25)] * 2,
            "modalite": ["3", "1", "3", "2", "1a", "1"],
            "type_campagne": ["usuelle", "usuelle", "complémentaire", "complémentaire",
                              "usuelle", "usuelle"],
        }
    )  # fmt: skip
    table = onde.calculer(obs, stations, {"2026-W30", "2026-W31", "2026-W35"}).set_index("semaine")
    assert table.loc["2026-W30", "valeur"] == 1.0  # campagne du 24, la plus récente
    detail = json.loads(str(table.loc["2026-W30", "detail"]))
    assert detail == {"date_campagne": "2026-07-24", "type_campagne": "complémentaire",
                      "n_assec": 1, "n_rupture": 1}  # fmt: skip
    assert table.loc["2026-W35", "valeur"] == 0.0
    assert "2026-W31" not in table.index  # pas de campagne : hors période, jamais zéro


def test_moyenne_par_zone_des_stations_retenues() -> None:
    par_station = pd.DataFrame(
        {
            "station_id": ["piezo:A", "piezo:B", "piezo:C"],
            "semaine": "2026-W39",
            "indice": "ips",
            "valeur": [-1.0, -2.0, 3.0],
            "dans_composite": [True, True, False],  # C : mesure trop ancienne (D1)
        }
    )
    stations = pd.DataFrame({"station_id": ["piezo:A", "piezo:B", "piezo:C"], "zone_id": "Z"})
    zone = composite.par_zone(par_station, stations).iloc[0]
    assert zone["valeur"] == pytest.approx(-1.5) and zone["n_stations"] == 2
    assert json.loads(str(zone["detail"])) == {"stations": ["piezo:A", "piezo:B"]}


def test_composite_renormalise_les_poids(config_z: Config) -> None:
    par_zone = pd.DataFrame(
        {
            "zone_id": "Z",
            "semaine": ["2026-W39"] * 3 + ["2026-W40"] * 3,
            "indice": ["spi_1", "spi_3", "debit", "spi_3", "ips", "debit"],
            "valeur": [5.0, -1.0, -2.0, 0.5, 1.0, -1.0],
        }
    )
    table = composite.composite(config_z, par_zone).set_index("semaine")
    # IPS absent : poids 0,4 et 0,3 ramenés à 4/7 et 3/7 ; le SPI 1 mois n'entre pas
    assert table.loc["2026-W39", "valeur"] == pytest.approx((0.4 * -1 + 0.3 * -2) / 0.7)
    detail = json.loads(str(table.loc["2026-W39", "detail"]))
    assert detail["manquantes"] == ["ips"] and detail["partiel"]
    assert detail["n_composantes"] == 2
    assert detail["composantes"]["spi_3"]["poids_applique"] == pytest.approx(0.5714)
    complet = json.loads(str(table.loc["2026-W40", "detail"]))
    assert not complet["partiel"] and table.loc["2026-W40", "valeur"] == pytest.approx(0.2)


def test_restandardisation_par_le_rang_de_la_zone(config_z: Config) -> None:
    # Indice de zone peu dispersé sur 1991-2020 (de -0,5 à 0,5) : la semaine la plus basse
    # de la référence passe en classe 1 ; avant 1991-2020 : pas d'année de référence
    semaines = [f"{a}-W{s:02d}" for a in range(1991, 2021) for s in range(1, 53)]
    valeurs = np.linspace(-0.5, 0.5, len(semaines))
    brutes = pd.DataFrame(
        {"zone_id": "Z", "semaine": semaines, "indice": "ips", "valeur": valeurs,
         "n_stations": 2, "detail": '{"stations": ["piezo:A", "piezo:B"]}'}
    )  # fmt: skip
    refs = rang.references(config_z, brutes)
    assert refs[["indice", "n_semaines", "periode_ref"]].values.tolist() == [
        ["ips", 1560, "1991-2020"]
    ]
    semaine = brutes[brutes["semaine"].isin(["1991-W01", "2005-W30", "2020-W52"])]
    resultat = rang.restandardiser(semaine, refs)
    assert resultat.columns.tolist() == brutes.columns.tolist()
    assert resultat["valeur"].round(2).tolist() == [-3.2, -0.04, 3.2]  # bornées par le rang
    detail = json.loads(resultat["detail"].iloc[0])
    assert detail == {"stations": ["piezo:A", "piezo:B"], "valeur_brute": -0.5,
                      "reference": "1991-2020", "hors_reference": False}  # fmt: skip
    # zone sans référence : ligne retirée
    autre = semaine.assign(zone_id="SANS_REF")
    assert rang.restandardiser(autre, refs).empty


# --- De bout en bout -----------------------------------------------------------------------


def _donnees_synthetiques(config: Config) -> None:
    """Référentiels et observations de 2000 à 2026 pour une zone, deux mailles et trois
    stations (piézomètre, station hydrométrique, station ONDE)."""
    data = config.projet.chemins.data
    crs = config.projet.crs
    zone = box(0, 0, 16_000, 8_000)
    (data / "referentiels").mkdir(parents=True)
    gpd.GeoDataFrame({"zone_id": ["Z"]}, geometry=[zone], crs=crs).to_parquet(
        data / "referentiels" / "zones.parquet"
    )
    gpd.GeoDataFrame(
        {"maille_id": [1, 2]}, geometry=[box(0, 0, 8_000, 8_000), box(8_000, 0, 16_000, 8_000)],
        crs=crs,
    ).to_parquet(data / "referentiels" / "mailles_safran.parquet")  # fmt: skip
    gpd.GeoDataFrame(
        {"station_id": ["piezo:A", "hydro:Q", "onde:O"], "zone_id": "Z"},
        geometry=[Point(1_000, 1_000)] * 3, crs=crs,
    ).to_parquet(data / "referentiels" / "stations.parquet")  # fmt: skip

    alea = np.random.default_rng(3)
    dates = pd.date_range("2000-01-01", "2026-09-30", freq="D")
    saison = np.sin(2 * np.pi * dates.dayofyear / 365.25)
    brut = data / "raw"
    for source in ("piezo", "hydro", "onde", "meteo"):
        (brut / source).mkdir(parents=True)
    pd.DataFrame(
        {"maille_id": np.repeat([1, 2], len(dates)), "date": np.tile(dates.date, 2),
         "precip_mm": alea.gamma(0.6, 4.0, 2 * len(dates))}
    ).to_parquet(brut / "meteo" / "sim_2000.parquet")  # fmt: skip
    pd.DataFrame(
        {"station_id": "piezo:A", "date": dates.date,
         "niveau_ngf": 10 + saison + alea.normal(0, 0.3, len(dates))}
    ).to_parquet(brut / "piezo" / "chroniques_2000.parquet")  # fmt: skip
    pd.DataFrame(
        {"station_id": "hydro:Q", "date": dates.date,
         "qmj_ls": np.exp(3 + saison + alea.normal(0, 0.5, len(dates)))}
    ).to_parquet(brut / "hydro" / "qmj_2000.parquet")  # fmt: skip
    pd.DataFrame(
        {"station_id": ["onde:O"], "date_campagne": [date(2026, 7, 24)], "modalite": ["3"],
         "type_campagne": ["usuelle"]}
    ).to_parquet(brut / "onde" / "observations_2026.parquet")  # fmt: skip


def test_calcul_et_idempotence(config_z: Config) -> None:
    _donnees_synthetiques(config_z)
    reference.calculer(config_z)
    tables = indices.calculer(config_z, "2025-W50", "2026-W39")
    assert len(tables["composite_zone"]) == 42  # une ligne par semaine (2025 en compte 52)

    dossier = indices.dossier(config_z)
    composites = pd.read_parquet(dossier / "composite_zone_2026.parquet")
    assert len(composites) == 39
    assert (composites["version_methodo"] == config_z.projet.indices.version_methodo).all()
    assert composites["classe"].between(1, 7).all()
    complets = composites["detail"].map(lambda d: json.loads(d)["n_composantes"] == 3)
    assert complets.all()
    zones = pd.read_parquet(dossier / "indice_zone_2026.parquet")
    assert set(zones["indice"]) == {"spi_1", "spi_3", "spi_6", "ips", "debit", "onde"}
    assert zones.loc[zones["indice"] == "onde", "classe"].isna().all()
    # indices de zone et composite restandardisés (D10) : valeur brute gardée dans le détail
    for table in (composites, zones[zones["indice"].isin(["ips", "debit"])]):
        details = table["detail"].map(json.loads)
        assert details.map(lambda d: "valeur_brute" in d and d["reference"] == "1991-2020").all()
    refs = pd.read_parquet(config_z.projet.chemins.data / "normales" / "rang_zone.parquet")
    assert sorted(refs["indice"]) == ["composite", "debit", "ips"]

    # relancer, en entier ou sur une partie des semaines, réécrit des fichiers identiques
    contenus = {f.name: f.read_bytes() for f in dossier.iterdir()}
    indices.calculer(config_z, "2026-W30", "2026-W39")
    indices.calculer(config_z, "2025-W50", "2026-W39")
    assert {f.name: f.read_bytes() for f in dossier.iterdir()} == contenus
