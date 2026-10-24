# ruff: noqa
"""V2.0 A : surfaces par classe de la BD Forêt V2 et du RPG 2025 sur le territoire (une couche par appel)."""

import os, warnings

warnings.filterwarnings("ignore")
import io, sys, requests, geopandas as gpd, pandas as pd

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
com = gpd.read_parquet("data/referentiels/communes.parquet")
terr = com.union_all()
bb = com.to_crs(4326).total_bounds
bbox = f"{bb[1]},{bb[0]},{bb[3]},{bb[2]},urn:ogc:def:crs:EPSG::4326"


def pages(layer, taille=5000):
    out, debut = [], 0
    while True:
        p = dict(
            SERVICE="WFS",
            VERSION="2.0.0",
            REQUEST="GetFeature",
            TYPENAMES=layer,
            OUTPUTFORMAT="application/json",
            SRSNAME="EPSG:2154",
            BBOX=bbox,
            COUNT=taille,
            STARTINDEX=debut,
            SORTBY=("id" if "FORESTINVENTORY" in layer else "num_parcel"),
        )
        r = requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=600)
        r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content))
        g = g.set_crs(2154) if g.crs is None else g.to_crs(2154)
        print(layer.split(":")[0], "page", debut, len(g), flush=True)
        if len(g) == 0:
            break
        out.append(g)
        debut += len(g)
        if len(g) < taille:
            break
    return pd.concat(out, ignore_index=True)


cible = sys.argv[1]
if cible == "bdforet":
    g = pages("LANDCOVER.FORESTINVENTORY.V2:formation_vegetale")
else:
    g = pages("IGNF_RPG_GRANDES-CATEGORIES-PARCELLES_2025:grandes_categories_parcelles")
print(
    "colonnes:",
    [c for c in g.columns if c != "geometry"],
    "; objets bruts",
    len(g),
    "; doublons d'id",
    int(g.id.duplicated().sum()),
)
g = g.drop_duplicates("id")
g = g[g.geometry.representative_point().within(terr)].copy()
g["ha"] = g.geometry.area / 1e4
g.to_parquet(f"{S}/{cible}.parquet")
print(cible, ": objets", len(g), "; surface", round(g.ha.sum()), "ha")
