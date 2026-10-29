# ruff: noqa
"""V2.0 marée, limites terre-mer de la BD TOPO (trait de côte, limites de salure des eaux, limites transversales de la mer). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import io, requests, geopandas as gpd, pandas as pd

com = gpd.read_parquet("data/referentiels/communes.parquet")
terr = com.union_all()
bb = com.to_crs(4326).total_bounds


def wfs(layer, **extra):
    p = dict(
        SERVICE="WFS",
        VERSION="2.0.0",
        REQUEST="GetFeature",
        TYPENAMES=layer,
        OUTPUTFORMAT="application/json",
        SRSNAME="EPSG:2154",
        COUNT=50000,
    )
    p.update(extra)
    r = requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=400)
    r.raise_for_status()
    g = gpd.read_file(io.BytesIO(r.content))
    return g.set_crs(2154) if g.crs is None else g.to_crs(2154)


bbox = f"{bb[1]},{bb[0]},{bb[3]},{bb[2]},urn:ogc:def:crs:EPSG::4326"
zps = wfs("patrinat_zps:zps", BBOX=bbox)
zps = zps[zps.intersects(terr)]
nom = next(c for c in zps.columns if c.lower() in ("sitename", "nom_site", "site_name"))
dom = (
    zps[zps[nom].str.contains("Marais poitevin|Marais Breton|Marais breton", case=False)]
    .geometry.union_all()
    .intersection(terr)
)
lm = (
    wfs("BDTOPO_V3:limite_terre_mer", BBOX=bbox, CQL_FILTER="type_de_limite IS NOT NULL")
    if False
    else wfs("BDTOPO_V3:limite_terre_mer", BBOX=bbox)
)
lm.to_parquet(f"{os.environ.get('V20_SORTIE', 'rasters/v2_0')}/limite_terre_mer.parquet")
lm["d"] = lm.geometry.distance(dom)
t = lm[lm.type_de_limite.notna()].copy()
print("limites spéciales :", len(t))
for ty, g in t.groupby("type_de_limite"):
    print(
        f"  {ty}: {len(g)} lignes ; dans le domaine (distance 0) : {(g.d == 0).sum()} ; à moins de 500 m : {(g.d < 500).sum()} ; à moins de 2 km : {(g.d < 2000).sum()}"
    )
c = lm[lm.type_de_limite.isna() & (lm.niveau == "Plus hautes eaux")]
print(
    "trait de côte (plus hautes eaux) :",
    len(c),
    "lignes ; à moins de 500 m du domaine :",
    int((c.d < 500).sum()),
)
b = lm[lm.niveau == "Plus basses eaux"]
print(
    "plus basses eaux :", len(b), "lignes ; à moins de 500 m du domaine :", int((b.d < 500).sum())
)
