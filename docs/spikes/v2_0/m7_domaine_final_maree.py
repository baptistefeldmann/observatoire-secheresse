# ruff: noqa
"""V2.0 marée, domaine final hors marée (réseau maritime + marge, pixels corrélés), contrôle et image. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import sys, io, time, requests, numpy as np, pandas as pd, geopandas as gpd
from affine import Affine
from rasterio.features import geometry_mask, rasterize
from scipy import ndimage as ndi, stats
import rasterio, rasterio.shutil, os

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
RESEAU = os.environ.get("V20_RESEAU", "D")  # variante du réseau maritime (m3) : D retenue
OUT = S
MARGE = float(sys.argv[1])
SEUIL = -0.5
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
net = gpd.read_parquet(f"{S}/maree/atteint_{RESEAU}.parquet").geometry
foret = gpd.read_parquet(f"{S}/bdforet.parquet")
ORB = {"poitevin": (8, 30), "breton": (81, 30)}


def wfs(layer, bb):
    p = dict(
        SERVICE="WFS",
        VERSION="2.0.0",
        REQUEST="GetFeature",
        TYPENAMES=layer,
        OUTPUTFORMAT="application/json",
        SRSNAME="EPSG:2154",
        BBOX=f"{bb[1]},{bb[0]},{bb[3]},{bb[2]},urn:ogc:def:crs:EPSG::4326",
        COUNT=5000,
        SORTBY="cleabs" if "BDTOPO" in layer else "id",
    )
    for t in range(8):
        try:
            r = requests.get("https://data.geopf.fr/wfs/ows", params=p, timeout=300)
            r.raise_for_status()
            g = gpd.read_file(io.BytesIO(r.content))
            return g.set_crs(2154) if g.crs is None else g.to_crs(2154)
        except Exception as e:
            print("reprise", str(e)[:80], flush=True)
            time.sleep(5 * (t + 1))
    raise RuntimeError


ha = 0.09
for marais, orbs in ORB.items():
    geom = dom.loc[marais].geometry
    z = {o: np.load(f"{S}/maree/r_{marais}_{o}.npz") for o in orbs}
    p0 = np.load(f"{S}/maree/pile_{marais}_{orbs[0]}.npz")
    tr = Affine(*p0["transform"])
    shp = tuple(p0["shape"])
    dans = geometry_mask([geom], out_shape=shp, transform=tr, invert=True)
    bb = tuple(gpd.GeoSeries([geom.envelope], crs=2154).to_crs(4326).total_bounds)
    estran = wfs("BDTOPO_V3:zone_d_estran", bb)
    clc = wfs("LANDCOVER.CLC18_FR:clc18_fr", bb)
    col = next(c for c in clc.columns if c.lower().startswith("code"))

    def ras(gdf):
        gg = [g for g in gdf.geometry if not g.is_empty]
        return (
            rasterize(
                [(g, 1) for g in gg], out_shape=shp, transform=tr, fill=0, all_touched=False
            ).astype(bool)
            if gg
            else np.zeros(shp, bool)
        )

    m_estran = ras(estran)
    m_foret = ras(foret[foret.intersects(geom)])
    c = clc[col].astype(str)
    m_salants = ras(clc[c == "422"])
    m_inter = ras(clc[c.isin(["423", "331"])])
    dN = z[orbs[0]]["dN"]
    m_reseau = dN <= MARGE
    tide = np.zeros(shp, bool)
    for o in orbs:
        r = z[o]["r"]
        tide |= np.isfinite(r) & (r < SEUIL)
    m_tide = ndi.binary_dilation(tide, iterations=1)
    couches = [
        ("marais salants (CLC 422)", m_salants),
        ("estran, zones intertidales, plages et dunes", m_estran | m_inter),
        (f"réseau maritime + {MARGE:.0f} m", m_reseau),
        ("pixels corrélés à la marée (r < -0,5, +30 m)", m_tide),
    ]
    tot = dans.sum() * ha
    deja = np.zeros(shp, bool)
    print(f"\n=== {marais} : domaine {tot:.0f} ha")
    for nom, m in couches:
        nouveau = m & dans & ~deja
        deja |= m
        print(
            f"   {nom:48s} retire {nouveau.sum() * ha:7.0f} ha (seule, hors couches précédentes) ; seule : {(m & dans).sum() * ha:7.0f} ha"
        )
    final = dans & ~deja
    print(
        f"   DOMAINE FINAL : {final.sum() * ha:.0f} ha ({final.sum() / dans.sum():.1%} du domaine, retiré {(dans & deja).sum() * ha:.0f} ha)"
    )
    final_crue = (
        final & ~m_foret
    )  # domaine de la surface de crue : sans la BD Forêt (reste dans le NDVI et le NDMI)
    print(
        f"   forêt (BD Forêt) dans le domaine final : {(final & m_foret).sum() * ha:.0f} ha ; DOMAINE DE CRUE (sans forêt) : {final_crue.sum() * ha:.0f} ha"
    )
    np.savez_compressed(
        f"{S}/maree/final_{marais}.npz",
        final=final,
        final_crue=final_crue,
        deja=deja,
        dans=dans,
        transform=np.array(tr)[:6],
    )
    # contrôle : corrélation par passage dans le domaine final, et part de pixels corrélés restants
    for o in orbs:
        p = np.load(f"{S}/maree/pile_{marais}_{o}.npz")
        db = p["db"].astype("float32")
        h = p["h"]
        med = np.nanmedian(db, axis=0)
        wet = (db < -16) & ((db - med) < -3) & np.isfinite(db)
        a = wet[:, final].sum(1) * ha
        ok = np.isfinite(h) & np.isfinite(a)
        rr, pv = stats.pearsonr(a[ok], h[ok])
        rest = z[o]["r"][final]
        rest = rest[np.isfinite(rest)]
        print(
            f"   orbite {o} : passages {ok.sum()} ; r(surface détectée, hauteur) = {rr:+.2f} (p = {pv:.2f}) ; pixels r<-0,5 restants {int((rest < SEUIL).sum())} sur {rest.size}"
        )
    # image : vert = domaine de crue ; vert foncé = forêt (hors domaine de crue) ; rouge clair = réseau + marge ; rouge = pixels corrélés ; ocre = marais salants ; violet = estran ; bleu = réseau
    img = np.zeros(shp + (3,), "uint8") + 255
    img[dans] = (215, 215, 215)
    img[final] = (140, 200, 140)
    img[final & m_foret] = (60, 120, 60)
    img[dans & m_salants] = (230, 190, 120)
    img[dans & (m_estran | m_inter)] = (200, 160, 220)
    img[dans & m_reseau & ~m_salants & ~(m_estran | m_inter)] = (240, 130, 130)
    img[dans & m_tide & ~m_reseau & ~m_salants] = (200, 0, 0)
    lig = ras(gpd.GeoDataFrame(geometry=net.clip(geom.envelope).buffer(15), crs=2154))
    img[lig] = (0, 60, 220)
    k = 2
    a = np.kron(img, np.ones((k, k, 1), "uint8"))
    tmp = f"{OUT}/maree_domaine_{marais}.tif"
    with rasterio.open(
        tmp, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=3, dtype="uint8"
    ) as dst:
        dst.write(np.moveaxis(a, 2, 0))
    rasterio.shutil.copy(tmp, f"{OUT}/maree_domaine_{marais}.png", driver="PNG")
    os.remove(tmp)
