# ruff: noqa
"""V2.0 marée, tronçons hydrographiques de la BD TOPO (WFS) autour du domaine, avec salinité, fictif, largeur et nœuds. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import io, time, requests, geopandas as gpd, pandas as pd, sys

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
os.makedirs(f"{S}/maree", exist_ok=True)
dom = gpd.read_parquet(f"{S}/domaine.parquet")
env = dom.geometry.union_all().buffer(8000)
bb = gpd.GeoSeries([env], crs=2154).to_crs(4326).total_bounds
bbox = f"{bb[1]},{bb[0]},{bb[3]},{bb[2]},urn:ogc:def:crs:EPSG::4326"


def page(layer, start, n=5000):
    p = dict(
        SERVICE="WFS",
        VERSION="2.0.0",
        REQUEST="GetFeature",
        TYPENAMES=layer,
        OUTPUTFORMAT="application/json",
        SRSNAME="EPSG:2154",
        BBOX=bbox,
        COUNT=n,
        STARTINDEX=start,
        SORTBY="cleabs",
    )
    for t in range(8):
        try:
            r = requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=300)
            r.raise_for_status()
            g = gpd.read_file(io.BytesIO(r.content))
            return g.set_crs(2154) if g.crs is None else g.to_crs(2154)
        except Exception as e:
            print("reprise", t, e, flush=True)
            time.sleep(5 * (t + 1))
    raise RuntimeError


def tout(layer):
    out, s = [], 0
    while True:
        g = page(layer, s)
        g = g[
            [
                c
                for c in (
                    "cleabs",
                    "nature",
                    "persistance",
                    "fictif",
                    "sens_de_l_ecoulement",
                    "etat_de_l_objet",
                    "salinite",
                    "statut",
                    "fosse",
                    "navigabilite",
                    "classe_de_largeur",
                    "reseau_principal_coulant",
                    "lien_vers_noeud_hydrographique_ini",
                    "lien_vers_noeud_hydrographique_fin",
                    "geometry",
                )
                if c in g.columns
            ]
        ].copy()
        for c in g.columns:
            if c != "geometry":
                g[c] = g[c].astype(str)
        g.to_parquet(f"{S}/maree/page_{s:06d}.parquet")
        out.append(g)
        print(layer, s, len(g), flush=True)
        if len(g) < 5000:
            break
        s += 5000
    return pd.concat(out, ignore_index=True)


t = tout("BDTOPO_V3:troncon_hydrographique")
t = t[t.intersects(env)]
print("tronçons :", len(t), [c for c in t.columns if c != "geometry"], flush=True)
t.to_parquet(f"{S}/maree/troncons.parquet")
for c in (
    "nature",
    "persistance",
    "fictif",
    "salinite",
    "statut",
    "sens_de_l_ecoulement",
    "classe_de_largeur",
):
    if c in t:
        print(c, t[c].value_counts(dropna=False).head(10).to_dict())
print("terminé")
