"""Export statique du dashboard (GitHub Pages) : `make site`, publié par `make pages`.

Interroge l'API en interne (mêmes requêtes, même logique) et écrit dans le dossier de sortie :
- le dashboard (`index.html`, `app.js`, `style.css`) en mode statique, avec une balise qui
  demande aux moteurs de recherche de ne pas indexer le site ;
- `donnees/` : contours des zones et des stations (une seule fois), indices et synthèse de
  chaque semaine (un fichier par année), séries complètes par zone et par station.

Les retenues et ONDE prennent, pour chaque semaine, le dernier relevé au dimanche, comme
`GET /stations`. Lancement : `python -m api.export <dossier>` (PostGIS démarré, `.env`)."""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from api.app import DASHBOARD, app
from pipeline.indices.commun import dimanche

INDICES_ZONE = ("composite", "spi_3", "ips", "debit", "onde")  # ceux qu'affiche le dashboard
PROPRIETES_ZONE = ("zone_id", "libelle", "type_zone", "ponderations")
PROPRIETES_STATION = ("station_id", "source", "code", "libelle", "en_service", "zone_id")
INDICATEUR_ZONE = ("valeur", "classe", "n_composantes", "partiel", "manquantes", "composantes")
INDICATEUR_STATION = (
    "indice", "valeur", "classe", "date_mesure", "dans_composite", "hors_reference",
)  # fmt: skip


def nom_fichier(station_id: str) -> str:
    """Nom de fichier sûr : « piezo:05634X0013/SF3 » -> « piezo_05634X0013_SF3 »."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", station_id)


def ecrire(chemin: Path, donnees: Any) -> int:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(donnees, ensure_ascii=False, separators=(",", ":"))
    chemin.write_text(texte, encoding="utf-8")
    return len(texte.encode("utf-8"))


def garder(proprietes: dict[str, Any], cles: tuple[str, ...]) -> dict[str, Any]:
    return {c: proprietes[c] for c in cles if proprietes.get(c) is not None}


def derniers_au_dimanche(
    points: list[dict[str, Any]], semaines: list[str]
) -> dict[str, dict[str, Any]]:
    """Pour chaque semaine (ordre croissant), le dernier point daté du dimanche ou avant."""
    resultat: dict[str, dict[str, Any]] = {}
    i, dernier = 0, None
    for semaine in semaines:
        fin = dimanche(semaine).isoformat()
        while i < len(points) and points[i]["date"] <= fin:
            dernier = points[i]
            i += 1
        if dernier is not None:
            resultat[semaine] = dernier
    return resultat


def page_statique(html: str) -> str:
    """Dashboard en mode statique, non indexé par les moteurs de recherche."""
    html = html.replace(
        '<meta name="viewport"',
        '<meta name="robots" content="noindex, nofollow">\n  <meta name="viewport"',
        1,
    )
    return html.replace(
        '<script type="module" src="app.js"></script>',
        "<script>window.OBSERVATOIRE = { statique: true };</script>\n"
        '  <script type="module" src="app.js"></script>',
        1,
    )


def exporter(sortie: Path, client: TestClient) -> dict[str, int]:
    """Écrit le site dans `sortie` (vidé au préalable) ; renvoie la taille par rubrique."""

    def lire(chemin: str) -> Any:
        reponse = client.get(chemin)
        reponse.raise_for_status()
        return reponse.json()

    shutil.rmtree(sortie, ignore_errors=True)
    donnees = sortie / "donnees"
    tailles: dict[str, int] = defaultdict(int)
    semaines = sorted(lire("/semaines")["semaines"])
    for nom, chemin in (("accueil", "/"), ("classes", "/classes")):
        tailles["generalites"] += ecrire(donnees / f"{nom}.json", lire(chemin))
    tailles["generalites"] += ecrire(donnees / "semaines.json", lire("/semaines"))

    # Par semaine : indicateurs des zones et des stations, synthèse
    hebdo: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"zones": {}, "stations": {}, "synthese": None}
    )

    zones = lire("/zones")
    for zone in zones["features"]:
        zone["properties"] = garder(zone["properties"], PROPRIETES_ZONE)
        zone_id = zone["properties"]["zone_id"]
        series = {
            indice: lire(f"/zones/{zone_id}/series?indice={indice}")["points"]
            for indice in INDICES_ZONE
        }
        tailles["series_zones"] += ecrire(donnees / "series" / "zones" / f"{zone_id}.json", series)
        for point in series["composite"]:
            hebdo[point["semaine"]]["zones"][zone_id] = garder(point, INDICATEUR_ZONE)
    tailles["contours"] += ecrire(donnees / "zones.geojson", zones)

    stations = lire("/stations")
    for station in stations["features"]:
        station["properties"] = garder(station["properties"], PROPRIETES_STATION)
        station_id = station["properties"]["station_id"]
        station["properties"]["fichier"] = nom_fichier(station_id)
        serie = lire(f"/stations/{station_id}/series")
        tailles["series_stations"] += ecrire(
            donnees / "series" / "stations" / f"{nom_fichier(station_id)}.json", serie
        )
        source, points = station["properties"]["source"], serie["chronique"]["points"]
        for indice in serie["indices"]:
            hebdo[indice["semaine"]]["stations"][station_id] = garder(indice, INDICATEUR_STATION)
        if source == "retenue":
            for semaine, p in derniers_au_dimanche(points, semaines).items():
                hebdo[semaine]["stations"][station_id] = {
                    "date_releve": p["date"], "volume_m3": p["volume_m3"],
                    "capacite_m3": p["capacite_m3"], "remplissage_pct": p["valeur"],
                }  # fmt: skip
        elif source == "onde":
            for semaine, p in derniers_au_dimanche(points, semaines).items():
                hebdo[semaine]["stations"][station_id] = {
                    "date_campagne": p["date"],
                    "modalite": p["valeur"],
                }
    tailles["contours"] += ecrire(donnees / "stations.geojson", stations)

    for semaine in semaines:
        hebdo[semaine]["synthese"] = lire(f"/semaines/{semaine}/synthese")
    for annee in sorted({s[:4] for s in semaines}):
        tailles["semaines"] += ecrire(
            donnees / "semaines" / f"{annee}.json",
            {s: hebdo[s] for s in semaines if s.startswith(annee)},
        )

    for fichier in ("app.js", "style.css"):
        shutil.copy(DASHBOARD / fichier, sortie / fichier)
    (sortie / "index.html").write_text(
        page_statique((DASHBOARD / "index.html").read_text(encoding="utf-8")), encoding="utf-8"
    )
    (sortie / ".nojekyll").touch()  # GitHub Pages : servir les fichiers tels quels
    return dict(tailles)


def principal() -> None:
    sortie = Path(sys.argv[1] if len(sys.argv) > 1 else "build/pages")
    debut = time.monotonic()
    tailles = exporter(sortie, TestClient(app))
    for rubrique, octets in tailles.items():
        print(f"{rubrique:<16} {octets / 1e6:7.1f} Mo")
    print(f"Site écrit dans {sortie} ({sum(tailles.values()) / 1e6:.0f} Mo, "
          f"{time.monotonic() - debut:.0f} s)")  # fmt: skip


if __name__ == "__main__":
    principal()
