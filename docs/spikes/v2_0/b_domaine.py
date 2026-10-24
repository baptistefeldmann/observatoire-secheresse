# ruff: noqa
"""V2.0 B (1/2) : domaine des marais = ZPS Marais poitevin + Marais breton ∩ territoire, moins marais salants, zones intertidales,
plages/dunes (CORINE 422, 423, 331) et estran (BD TOPO). Écrit domaine.parquet (EPSG:2154)."""

import os, warnings

warnings.filterwarnings("ignore")
import io, requests, geopandas as gpd, pandas as pd

V = os.environ.get("V20_SORTIE", "rasters/v2_0")
com = gpd.read_parquet("data/referentiels/communes.parquet")
terr = com.union_all()
bb = com.to_crs(4326).total_bounds
bbox = f"{bb[1]},{bb[0]},{bb[3]},{bb[2]},urn:ogc:def:crs:EPSG::4326"


def wfs(layer, **extra):
    p = dict(
        SERVICE="WFS",
        VERSION="2.0.0",
        REQUEST="GetFeature",
        TYPENAMES=layer,
        OUTPUTFORMAT="application/json",
        SRSNAME="EPSG:2154",
        BBOX=bbox,
        COUNT=5000,
    )
    p.update(extra)
    r = requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=600)
    r.raise_for_status()
    g = gpd.read_file(io.BytesIO(r.content))
    return g.set_crs(2154) if g.crs is None else g.to_crs(2154)


zps = wfs("patrinat_zps:zps")
zps = zps[zps.intersects(terr)]
nom = next(c for c in zps.columns if c.lower() in ("sitename", "nom_site", "site_name"))
parts = {}
for cle, motif in (("poitevin", "Marais poitevin"), ("breton", "Marais Breton|Marais breton")):
    parts[cle] = (
        zps[zps[nom].str.contains(motif, case=False)].geometry.union_all().intersection(terr)
    )


def pages(layer):
    out, debut = [], 0
    while True:
        g = wfs(layer, STARTINDEX=debut, SORTBY="id")
        out.append(g)
        debut += len(g)
        if len(g) < 5000:
            break
    return pd.concat(out, ignore_index=True)


clc = pages("LANDCOVER.CLC18_FR:clc18_fr")
clc = clc[clc.code_18.astype(str).isin(["422", "423", "331"])]
est = wfs("BDTOPO_V3:zone_d_estran")
retrait = pd.concat([clc.geometry, est.geometry]).union_all()
rows = []
for cle, g in parts.items():
    net = g.difference(retrait)
    rows.append(dict(marais=cle, geometry=net, ha_brut=g.area / 1e4, ha_net=net.area / 1e4))
    print(
        cle,
        "brut",
        round(g.area / 1e4),
        "ha ; net",
        round(net.area / 1e4),
        "ha ; retrait",
        round((g.area - net.area) / 1e4),
        "ha ; emprise",
        [round(x / 1000, 1) for x in net.bounds],
    )
gpd.GeoDataFrame(rows, crs=2154).to_parquet(f"{V}/domaine.parquet")
