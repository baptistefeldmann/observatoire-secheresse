# ruff: noqa
"""V2.0 masque d'eau permanente : effet sur la surface de crue (orbite 81, hivers 2023-2024 et 2024-2025) du masque de Sentinel-1 (n5), des surfaces d'eau permanentes de la BD TOPO, et des deux réunis. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 3.9)."""

import warnings

warnings.filterwarnings("ignore")
import os, numpy as np, geopandas as gpd, dask
import odc.stac, planetary_computer
from scipy import ndimage as ndi
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import geometry_mask, rasterize

os.environ.update(
    {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "GDAL_HTTP_MAX_RETRY": "8",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "GDAL_HTTP_TIMEOUT": "60",
        "VSI_CACHE": "TRUE",
    }
)
S = os.environ.get("V20_SORTIE", "rasters/v2_0")
ORBITE, HA = 81, 0.01
MARGE_PX = int(os.environ.get("V20_MARGE_PX", "1"))
HIVERS = [
    ("2023-12-01/2024-03-31", "2023-07-01/2023-09-30"),
    ("2024-12-01/2025-03-31", "2024-07-01/2024-09-30"),
]
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais")
hydro = gpd.read_parquet(f"{S}/surface_hydro.parquet")
hydro = hydro[
    hydro.persistance == "Permanent"
]  # les surfaces « intermittentes » (nature Marais) sont les prairies inondées elles-mêmes : à ne pas masquer
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")


def charger(its, gb):
    ds = odc.stac.load(
        its,
        bands=["vv"],
        geobox=gb,
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
        patch_url=planetary_computer.sign,
        dtype="float32",
        nodata=-32768,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        v = ds.vv.compute().values
    return np.where(np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan).astype(
        "float32"
    )


lisse = lambda x: ndi.median_filter(np.where(np.isfinite(x), x, np.nanmedian(x)), size=3)
for marais, ligne in dom.iterrows():
    geom = ligne.geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    m_s1 = np.load(f"{S}/masque_eau_permanente_{marais}.npz")["masque"]
    h = hydro[hydro.intersects(geom)]
    m_h = rasterize(
        [(g, 1) for g in h.geometry if not g.is_empty],
        out_shape=gb.shape,
        transform=gb.affine,
        fill=0,
    ).astype(bool)
    if MARGE_PX:
        m_h = ndi.binary_dilation(
            m_h, iterations=MARGE_PX
        )  # marge de pixels de 10 m autour des surfaces d'eau
    ha = lambda m: float((m & dans).sum() * HA)
    print(
        f"{marais} : masque S1 {ha(m_s1):.0f} ha, BD TOPO (marge {MARGE_PX} pixel) {ha(m_h):.0f} ha, réunis {ha(m_s1 | m_h):.0f} ha",
        flush=True,
    )
    for hiver, ete in HIVERS:
        sel = lambda p: [
            i
            for i in cl.search(collections=["sentinel-1-rtc"], bbox=bb, datetime=p).items()
            if i.properties["sat:relative_orbit"] == ORBITE
        ]
        ref = np.nanmedian(charger(sel(ete), gb), axis=0)
        db = charger(sel(hiver), gb)
        rf = lisse(ref)
        res = {"sans masque": [], "masque S1": [], "BD TOPO": [], "S1 + BD TOPO": []}
        for k in range(db.shape[0]):
            x = db[k]
            ok = np.isfinite(x) & np.isfinite(ref)
            xf = lisse(np.where(ok, x, np.nan))
            c0 = ((xf - rf) < -3) & (xf < -16) & (rf >= -16) & ok
            lab, _ = ndi.label(c0)
            tai = np.bincount(lab.ravel())
            crue = np.isin(lab, np.where(tai >= 10)[0]) & (lab > 0)
            res["sans masque"].append(ha(crue))
            res["masque S1"].append(ha(crue & ~m_s1))
            res["BD TOPO"].append(ha(crue & ~m_h))
            res["S1 + BD TOPO"].append(ha(crue & ~(m_s1 | m_h)))
        print(
            f"  hiver {hiver[:7]} ({db.shape[0]} passages) : "
            + " ; ".join(f"{k} {np.median(v):.0f} ha" for k, v in res.items()),
            flush=True,
        )
print("terminé")
