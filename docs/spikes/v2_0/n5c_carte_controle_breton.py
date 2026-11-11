# ruff: noqa
"""V2.0 masque d'eau permanente, contrôle visuel du Marais breton : ce que retirent les surfaces d'eau de la BD TOPO (permanentes et intermittentes) de la crue détectée par l'orbite 81 (hiver 2023-2024), statistiques par nature et par persistance, et trois cartes de contrôle (Sentinel-2 d'été et Sentinel-1 d'hiver). Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 3.9)."""

import warnings

warnings.filterwarnings("ignore")
import os, numpy as np, pandas as pd, geopandas as gpd, dask, rasterio, rasterio.shutil
import odc.stac, planetary_computer
from scipy import ndimage as ndi
from odc.geo.geobox import GeoBox
from pystac_client import Client
from rasterio.features import geometry_mask, rasterize
from shapely.geometry import box
from affine import Affine

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
ORBITE, HA, FEN = 81, 0.01, 3000
HIVER, ETE = "2023-12-01/2024-03-31", "2023-07-01/2023-09-30"
marais = "breton"
geom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais").loc[marais].geometry
hydro = gpd.read_parquet(f"{S}/surface_hydro.parquet")
hydro = hydro[hydro.intersects(geom)]
cl = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
ras = lambda gg, g=gb: rasterize(
    [(x, 1) for x in gg if not x.is_empty], out_shape=g.shape, transform=g.affine, fill=0
).astype(bool)
m_s1 = np.load(f"{S}/masque_eau_permanente_{marais}.npz")["masque"]
cat = {
    "permanent": ras(hydro[hydro.persistance == "Permanent"].geometry),
    "intermittent": ras(hydro[hydro.persistance == "Intermittent"].geometry),
}
ha = lambda m: float((m & dans).sum() * HA)
print(
    "surfaces d'eau de la BD TOPO dans le domaine :",
    {k: round(ha(v)) for k, v in cat.items()},
    "; par nature (ha) :",
)
for (p, n), g in hydro.groupby(["persistance", "nature"]):
    print(f"   {p:13s} {n:30s} {g.geometry.area.sum() / 1e4:8.0f} ha ({len(g)} polygones)")


def charger(its, g=gb, bande="vv"):
    ds = odc.stac.load(
        its,
        bands=[bande],
        geobox=g,
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
        patch_url=planetary_computer.sign,
        dtype="float32",
        nodata=-32768,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        v = ds[bande].compute().values
    return np.where(np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan).astype(
        "float32"
    ), [str(t)[:10] for t in ds.time.values]


sel = lambda p: [
    i
    for i in cl.search(collections=["sentinel-1-rtc"], bbox=bb, datetime=p).items()
    if i.properties["sat:relative_orbit"] == ORBITE
]
ref = np.nanmedian(charger(sel(ETE))[0], axis=0)
db, dates = charger(sel(HIVER))
lisse = lambda x: ndi.median_filter(np.where(np.isfinite(x), x, np.nanmedian(x)), size=3)
rf = lisse(ref)
crues = []
for k in range(db.shape[0]):
    x = db[k]
    ok = np.isfinite(x) & np.isfinite(ref)
    xf = lisse(np.where(ok, x, np.nan))
    c0 = ((xf - rf) < -3) & (xf < -16) & (rf >= -16) & ok
    lab, _ = ndi.label(c0)
    tai = np.bincount(lab.ravel())
    crues.append(np.isin(lab, np.where(tai >= 10)[0]) & (lab > 0))
tab = []
for d, c in zip(dates, crues):
    tab.append(
        dict(
            date=d,
            crue=ha(c),
            retire_permanent=ha(c & cat["permanent"]),
            retire_intermittent=ha(c & cat["intermittent"] & ~cat["permanent"]),
            retire_s1_seul=ha(c & m_s1 & ~cat["permanent"] & ~cat["intermittent"]),
        )
    )
tab = pd.DataFrame(tab).round(0)
print(tab.to_string())
print("médianes :", tab.drop(columns="date").median().round(0).to_dict())
# passage de référence pour les cartes : le plus grand
k0 = int(np.argmax([ha(c) for c in crues]))
print("passage des cartes :", dates[k0])
crue, x0 = crues[k0], db[k0]
retire = crue & (cat["permanent"] | cat["intermittent"])
# fenêtres : les plus fortes surfaces retirées par la BD TOPO
cand = []
x_min, y_min, x_max, y_max = geom.bounds
for fx in np.arange(x_min, x_max, FEN):
    for fy in np.arange(y_min, y_max, FEN):
        c, r = ~gb.affine * (fx, fy + FEN)
        c, r = int(c), int(r)
        n = FEN // 10
        sl = (slice(max(r, 0), r + n), slice(max(c, 0), c + n))
        cand.append((float((retire[sl] & dans[sl]).sum() * HA), fx, fy))
cand.sort(reverse=True)
choisies = []
for s, fx, fy in cand:
    if all(abs(fx - a) > FEN or abs(fy - b) > FEN for _, a, b in choisies):
        choisies.append((s, fx, fy))
    if len(choisies) == 3:
        break
for n_fen, (s, fx, fy) in enumerate(choisies, 1):
    w = box(fx, fy, fx + FEN, fy + FEN)
    gw = GeoBox((FEN // 10, FEN // 10), Affine(10, 0, fx, 0, -10, fy + FEN), "EPSG:2154")
    # fond optique : Sentinel-2 d'été 2023, médiane des scènes claires
    bw = tuple(gpd.GeoSeries([w], crs=2154).to_crs(4326).total_bounds)
    its = [
        i
        for i in cl.search(
            collections=["sentinel-2-l2a"],
            bbox=bw,
            datetime="2023-07-01/2023-08-31",
            query={"eo:cloud_cover": {"lt": 15}},
        ).items()
        if i.properties.get("s2:processing_baseline")
    ]
    ds = odc.stac.load(
        its,
        bands=["B04", "B03", "B02", "SCL"],
        geobox=gw,
        groupby="solar_day",
        resampling="nearest",
        patch_url=planetary_computer.sign,
        dtype="uint16",
        nodata=0,
        chunks={"x": 512, "y": 512},
    ).compute()
    off = np.array(
        [-1000.0 if float(i.properties["s2:processing_baseline"]) >= 4.0 else 0.0 for i in its][
            : ds.time.size
        ],
        "float32",
    )[:, None, None]
    rgb = np.stack(
        [
            np.clip((ds[b].values.astype("float32") + off) / 10000.0, 0, None)
            for b in ("B04", "B03", "B02")
        ],
        -1,
    )
    ok = np.isin(ds.SCL.values, [4, 5, 6, 7, 11])[..., None]
    opt = np.nanmedian(np.where(ok, rgb, np.nan), axis=0)
    opt = (np.clip(np.nan_to_num(opt, nan=0.1) * 3.5, 0, 1) * 255).astype("uint8")
    n = FEN // 10
    c, r = ~gb.affine * (fx, fy + FEN)
    sl = (slice(round(r), round(r) + n), slice(round(c), round(c) + n))
    pad = lambda a: a[:n, :n]
    v = np.clip((x0[sl] + 25) / 20, 0, 1)
    sar = np.repeat((np.nan_to_num(v, nan=0.5)[..., None] * 255).astype("uint8"), 3, -1)
    perm, inter = cat["permanent"][sl], cat["intermittent"][sl]
    contour = lambda m: m & ~ndi.binary_erosion(m, iterations=1)
    img_s2 = opt.copy()
    img_s2[contour(perm)] = (255, 0, 0)
    img_s2[contour(inter & ~perm)] = (255, 160, 0)
    img_s1 = sar.copy()
    cr = crue[sl]
    img_s1[cr & ~retire[sl] & ~m_s1[sl]] = (0, 120, 255)
    img_s1[cr & m_s1[sl] & ~retire[sl]] = (255, 255, 0)
    img_s1[cr & perm] = (255, 0, 0)
    img_s1[cr & inter & ~perm] = (255, 160, 0)
    k_ = 3
    panneau = np.concatenate(
        [
            np.kron(img_s2, np.ones((k_, k_, 1), "uint8")),
            np.full((n * k_, 12, 3), 255, "uint8"),
            np.kron(img_s1, np.ones((k_, k_, 1), "uint8")),
        ],
        axis=1,
    )
    tmp = f"{S}/controle_breton_{n_fen}.tif"
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=panneau.shape[0],
        width=panneau.shape[1],
        count=3,
        dtype="uint8",
    ) as dst:
        dst.write(np.moveaxis(panneau, 2, 0))
    rasterio.shutil.copy(tmp, f"{S}/controle_breton_{n_fen}.png", driver="PNG")
    os.remove(tmp)
    print(
        f"carte {n_fen} : fenêtre L93 {fx / 1e3:.1f} / {fy / 1e3:.1f} km, {s:.0f} ha de crue retirés par la BD TOPO (permanent {ha_ if (ha_ := float((cr & perm).sum() * HA)) else 0:.0f} ha, intermittent {float((cr & inter & ~perm).sum() * HA):.0f} ha), {len(its)} scènes Sentinel-2",
        flush=True,
    )
print("terminé")
