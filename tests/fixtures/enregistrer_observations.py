"""Enregistre des réponses réelles, réduites, pour les tests d'ingestion (réseau requis).

    uv run python tests/fixtures/enregistrer_observations.py <dossier des CSV SIM 2026 et latest>

Un piézomètre et une station hydrométrique des fixtures de référentiel sur quelques jours de
septembre 2026, les observations ONDE depuis le 20/09/2026 et les campagnes du département,
et les lignes SIM des points de grille des fixtures (3 jours du fichier annuel, 2 du récent).
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

import geopandas as gpd
import httpx
import pandas as pd

ICI = Path(__file__).parent
HUBEAU = "https://hubeau.eaufrance.fr/api"


def _json(url: str, params: dict[str, str | int]) -> dict[str, object]:
    reponse: dict[str, object] = httpx.get(url, params=params, timeout=300).json()
    return reponse


def main(dossier_sim: Path) -> None:
    (ICI / "observations").mkdir(exist_ok=True)
    fichiers: dict[str, tuple[str, dict[str, Any]]] = {
        "piezo_chroniques.json": (
            f"{HUBEAU}/v1/niveaux_nappes/chroniques",
            {"code_bss": "05068X0028/SP010", "date_debut_mesure": "2026-09-10",
             "date_fin_mesure": "2026-09-30", "size": 20000, "format": "json",
             "fields": "date_mesure,niveau_nappe_eau,statut"},
        ),
        "hydro_qmnj.json": (
            f"{HUBEAU}/v2/hydrometrie/obs_elab",
            {"code_entite": "M702241010", "grandeur_hydro_elab": "QmnJ",
             "date_debut_obs_elab": "2026-09-20", "size": 20000, "format": "json",
             "fields": "date_obs_elab,resultat_obs_elab,libelle_statut"},
        ),
        "onde_observations.json": (
            f"{HUBEAU}/v1/ecoulement/observations",
            {"code_departement": "85", "date_observation_min": "2026-09-20", "size": 5000,
             "format": "json"},
        ),
        "onde_campagnes.json": (
            f"{HUBEAU}/v1/ecoulement/campagnes",
            {"code_departement": "85", "size": 5000, "format": "json"},
        ),
    }  # fmt: skip
    for nom, (url, params) in fichiers.items():
        page = _json(url, params)
        page["next"] = None  # une seule page
        (ICI / "observations" / nom).write_text(json.dumps(page, ensure_ascii=False, indent=1))

    points = gpd.read_file(ICI / "sim" / "SHP_SIM_FRANCE.shp")[["lambx", "lamby"]]
    cles = points.rename(columns={"lambx": "LAMBX", "lamby": "LAMBY"})
    for source, cible, jours in [
        ("QUOT_SIM2_2026.csv.gz", "QUOT_SIM2_2026.csv.gz", [20260924, 20260925, 20260926]),
        ("QUOT_SIM2_latest.csv.gz", "QUOT_SIM2_latest.csv.gz", [20260926, 20260927]),
    ]:
        table = pd.read_csv(dossier_sim / source, sep=";")
        extrait = table.merge(cles, on=["LAMBX", "LAMBY"])
        extrait = extrait[extrait["DATE"].isin(jours)]
        with gzip.open(ICI / "sim" / cible, "wt") as f:
            extrait.to_csv(f, sep=";", index=False)
        print(cible, len(extrait), "lignes")

    jeu = json.loads((ICI / "sim" / "jeu_datagouv.json").read_text())
    titres = {r["title"] for r in jeu["resources"]}
    for titre in ("QUOT_SIM2_2026", "QUOT_SIM2_latest"):
        if titre not in titres:
            jeu["resources"].append({"title": titre, "url": f"https://sim.test/{titre}.csv.gz"})
    (ICI / "sim" / "jeu_datagouv.json").write_text(json.dumps(jeu, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
