"""Spikes V0 n°2 et n°3 : profondeur d'historique Hub'Eau et éligibilité à la période de référence.

Télécharge l'historique complet des chroniques piézométriques et des QmnJ des stations du
département configuré, puis produit un tableau de synthèse par station.

    uv run python docs/spikes/hubeau_historique.py --cache <dossier> --sortie <dossier>

Les réponses brutes sont mises en cache (un JSON par station) : relancer le script ne
re-télécharge rien. Script jetable, hors pipeline.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.config import charger_config

CONFIG = charger_config()
DEP = CONFIG.projet.territoire.code_departement
REF = CONFIG.projet.periode_reference.hydro_meteo
URL_PIEZO = CONFIG.sources.hubeau.piezometrie
URL_HYDRO = CONFIG.sources.hubeau.hydrometrie

# Critères d'année exploitable, propres au spike (à fixer ensuite dans la méthodologie)
MOIS_MIN_PIEZO = 10  # mois avec au moins une mesure
JOURS_MIN_HYDRO = 330  # jours de QmnJ

client = httpx.Client(timeout=CONFIG.sources.http.timeout_s * 3)


@retry(
    stop=stop_after_attempt(CONFIG.sources.http.tentatives),
    wait=wait_exponential(min=2, max=60),
)
def _get(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    r = client.get(url, params=params)
    r.raise_for_status()
    resultat: dict[str, Any] = r.json()
    return resultat


def _en_cache(chemin: Path, telecharger: Any) -> tuple[list[dict[str, Any]], float]:
    if chemin.exists():
        contenu = json.loads(chemin.read_text())
        return contenu["data"], contenu["duree_s"]
    debut = time.perf_counter()
    data = telecharger()
    duree = time.perf_counter() - debut
    chemin.write_text(json.dumps({"data": data, "duree_s": duree}))
    return data, duree


def stations_piezo() -> list[dict[str, Any]]:
    d = _get(URL_PIEZO + "stations", {"code_departement": DEP, "size": 1000, "format": "json"})
    assert d["count"] == len(d["data"])
    return list(d["data"])


def chronique_piezo(code_bss: str) -> list[dict[str, Any]]:
    """Une seule page suffit si la station a moins de 20 000 mesures (vérifié)."""
    d = _get(
        URL_PIEZO + "chroniques",
        {
            "code_bss": code_bss,
            "size": 20000,
            "format": "json",
            "fields": "date_mesure,niveau_nappe_eau,profondeur_nappe,statut,qualification",
        },
    )
    if d["count"] > 20000:
        raise RuntimeError(f"{code_bss} : {d['count']} mesures, découpage par période nécessaire")
    return list(d["data"])


def stations_hydro() -> list[dict[str, Any]]:
    d = _get(
        URL_HYDRO + "referentiel/stations",
        {"code_departement": DEP, "size": 1000, "format": "json"},
    )
    assert d["count"] == len(d["data"])
    return list(d["data"])


def qmnj(code_station: str) -> list[dict[str, Any]]:
    """Pagination par curseur (`next`) jusqu'à épuisement."""
    params: dict[str, Any] | None = {
        "code_entite": code_station,
        "grandeur_hydro_elab": "QmnJ",
        "size": 20000,
        "format": "json",
        "fields": "date_obs_elab,resultat_obs_elab,libelle_statut,code_qualification",
    }
    url: str | None = URL_HYDRO + "obs_elab"
    data: list[dict[str, Any]] = []
    attendu = None
    while url:
        d = _get(url, params)
        attendu = d["count"] if attendu is None else attendu
        data.extend(d["data"])
        url, params = d.get("next"), None
    if attendu is not None and len(data) != attendu:
        raise RuntimeError(f"{code_station} : {len(data)} lignes reçues pour {attendu} annoncées")
    return data


def _annees(dates: pd.Series, critere: str) -> pd.Series:
    """Années exploitables selon le critère du spike."""
    if dates.empty:
        return pd.Series(dtype=int)
    if critere == "piezo":
        mois = dates.dt.to_period("M").drop_duplicates()
        par_an = mois.dt.year.value_counts()
        return par_an[par_an >= MOIS_MIN_PIEZO].index.to_series().sort_values()
    par_an = dates.drop_duplicates().dt.year.value_counts()
    return par_an[par_an >= JOURS_MIN_HYDRO].index.to_series().sort_values()


def synthese(dates: pd.Series, critere: str, aujourd_hui: date) -> dict[str, Any]:
    annees = _annees(dates, critere)
    ref = annees[(annees >= REF.debut) & (annees <= REF.fin)]
    ecarts = dates.sort_values().diff().dt.days.dropna()
    return {
        "premiere": dates.min().date() if len(dates) else None,
        "derniere": dates.max().date() if len(dates) else None,
        "n_mesures": len(dates),
        "pas_median_j": float(ecarts.median()) if len(ecarts) else None,
        "annees_exploitables": len(annees),
        "annees_ref": len(ref),
        "retard_j": (aujourd_hui - dates.max().date()).days if len(dates) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args()
    for sous in ("piezo", "hydro"):
        (args.cache / sous).mkdir(parents=True, exist_ok=True)
    args.sortie.mkdir(parents=True, exist_ok=True)
    aujourd_hui = date.today()

    lignes = []
    for s in stations_piezo():
        code = s["code_bss"]
        data, duree = _en_cache(
            args.cache / "piezo" / f"{code.replace('/', '_')}.json",
            lambda c=code: chronique_piezo(c),
        )
        df = pd.DataFrame(data)
        dates = pd.to_datetime(df["date_mesure"]) if len(df) else pd.Series(dtype="datetime64[ns]")
        brut = (df["statut"] == "Donnée brute").mean() if len(df) else None
        lignes.append(
            {
                "source": "piezo",
                "code": code,
                "libelle": s["libelle_pe"],
                "masse_eau": ", ".join(s.get("noms_masse_eau_edl") or []),
                "duree_s": round(duree, 1),
                "part_brute": brut,
                **synthese(dates, "piezo", aujourd_hui),
            }
        )
        print(f"piezo {code:<20} {len(df):>6} mesures  {duree:5.1f} s")

    for s in stations_hydro():
        code = s["code_station"]
        data, duree = _en_cache(args.cache / "hydro" / f"{code}.json", lambda c=code: qmnj(c))
        df = pd.DataFrame(data)
        dates = (
            pd.to_datetime(df["date_obs_elab"]) if len(df) else pd.Series(dtype="datetime64[ns]")
        )
        valide = (df["libelle_statut"] == "Donnée validée").mean() if len(df) else None
        lignes.append(
            {
                "source": "hydro",
                "code": code,
                "libelle": s["libelle_station"],
                "en_service": s["en_service"],
                "cours_eau": s.get("libelle_cours_eau"),
                "duree_s": round(duree, 1),
                "part_validee": valide,
                **synthese(dates, "hydro", aujourd_hui),
            }
        )
        print(f"hydro {code:<20} {len(df):>6} QmnJ     {duree:5.1f} s")

    tableau = pd.DataFrame(lignes)
    tableau.to_csv(args.sortie / "hubeau_historique.csv", index=False)
    print(f"\n{len(tableau)} stations -> {args.sortie / 'hubeau_historique.csv'}")


if __name__ == "__main__":
    main()
