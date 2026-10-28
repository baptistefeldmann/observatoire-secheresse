# ruff: noqa
"""V2.0 D : contrôle visuel. Image Sentinel-2 en couleurs, VV, crue vue par S2 et crue détectée par S1, sur la zone où S1 « sur-détecte » le plus."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import pandas as pd, time, datetime as dt, rasterio, rasterio.shutil
from rasterio.transform import from_origin

dom = gpd.read_parquet(f"{V}/domaine.parquet").set_index("marais")
com = gpd.read_parquet("data/referentiels/communes.parquet")
dev = com[
    com.nom.isin(["La Bretonnière-la-Claye", "Lairoux", "Curzon", "La Couture"])
].geometry.union_all()
CAS = [
    ("breton", dt.date(2021, 1, 8), 103, "breton_2021-01-08_o103", None),
    ("poitevin", dt.date(2021, 1, 8), 8, "poitevin_reste_2021-01-08_o8", "reste"),
    ("breton", dt.date(2024, 1, 6), 81, "breton_2024-01-06_o81", None),
]


def retry(f):
    for t in range(6):
        try:
            return f()
        except Exception as e:
            time.sleep(5 * (t + 1))
    raise RuntimeError


def charger(gb, items, bandes, dtype="uint16", nodata=0):
    ds = odc.stac.load(
        items,
        bands=bandes,
        geobox=gb,
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
        resampling={"*": "nearest"},
        patch_url=planetary_computer.sign,
        dtype=dtype,
        nodata=nodata,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        return ds.compute()


def png(rgb, chemin, zoom=2):
    a = np.kron(rgb, np.ones((zoom, zoom, 1), "uint8"))
    tmp = chemin.replace(".png", ".tif")
    with rasterio.open(
        tmp, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=3, dtype="uint8"
    ) as dst:
        dst.write(np.moveaxis(a, 2, 0))
    rasterio.shutil.copy(tmp, chemin, driver="PNG")
    os.remove(tmp)


def etirer(x, lo=2, hi=98):
    l, h = np.nanpercentile(x, [lo, hi])
    return np.clip((x - l) / (h - l + 1e-9), 0, 1)


for marais, jour, orb, nom, sous in CAS:
    geom = dom.loc[marais].geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    if sous == "reste":
        dans &= geometry_mask([dev], out_shape=gb.shape, transform=gb.affine)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    an_ref = jour.year - 1
    s2 = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-2-l2a"], bbox=bb, datetime=f"{jour}/{jour}"
            ).items()
            if offset(i) is not None
        ]
    )
    ds = charger(gb, s2, ["B02", "B03", "B04", "B11", "SCL"])
    off = float(offset(s2[0]))
    refl = {
        b: np.clip((ds[b].values[0].astype("float32") + off) / 1e4, 0, None)
        for b in ("B02", "B03", "B04", "B11")
    }
    valide = (
        np.isin(ds.SCL.values[0], [4, 5, 6, 7]) & (ds.B03.values[0] > 0) & (ds.B11.values[0] > 0)
    )
    mn = (refl["B03"] - refl["B11"]) / (refl["B03"] + refl["B11"] + 1e-6)
    est = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-2-l2a"],
                bbox=bb,
                datetime=f"{an_ref}-08-01/{an_ref}-08-31",
                query={"eo:cloud_cover": {"lt": 60}},
            ).items()
            if offset(i) is not None
        ]
    )
    dse = charger(gb, est, ["B03", "B11", "SCL"])
    oe = np.array([offset(est[0])], "float32")
    g = np.clip((dse.B03.values.astype("float32") + oe) / 1e4, 0, None)
    s = np.clip((dse.B11.values.astype("float32") + oe) / 1e4, 0, None)
    me = np.where(np.isin(dse.SCL.values, [4, 5, 6, 7]), (g - s) / (g + s + 1e-6), np.nan)
    perm = np.nanmedian(me, axis=0) > 0
    eau_s2 = (mn > 0) & valide & ~perm
    s1j = retry(
        lambda: list(
            CL.search(
                collections=["sentinel-1-rtc"],
                bbox=bb,
                datetime=f"{jour - dt.timedelta(days=3)}/{jour + dt.timedelta(days=3)}",
            ).items()
        )
    )
    its = [i for i in s1j if i.properties["sat:relative_orbit"] == orb]
    x = charger(gb, its, ["vv"], "float32", -32768).vv.values[0]
    ete = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-1-rtc"], bbox=bb, datetime=f"{an_ref}-07-01/{an_ref}-09-30"
            ).items()
            if i.properties["sat:relative_orbit"] == orb
        ]
    )
    v = charger(gb, ete, ["vv"], "float32", -32768).vv.values
    ref = np.nanmedian(
        np.where(np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan), axis=0
    )
    ok = np.isfinite(x) & (x > 0)
    db = np.where(ok, 10 * np.log10(np.where(x > 0, x, 1)), np.nan)
    det = (db < -16) & ((db - ref) < -3) & (ref >= -16) & ok & ~perm
    fp = det & ~eau_s2 & valide & dans
    fn = eau_s2 & ~det & ok & dans
    # cellule de 4 km avec le plus de faux positifs
    T = 400
    best = (0, 0, 0)
    for r0 in range(0, gb.shape[0] - T, 100):
        for c0 in range(0, gb.shape[1] - T, 100):
            sub = dans[r0 : r0 + T, c0 : c0 + T]
            if sub.mean() < 0.5:
                continue
            n = int(fp[r0 : r0 + T, c0 : c0 + T].sum())
            if n > best[0]:
                best = (n, r0, c0)
    n, r0, c0 = best
    sl = (slice(r0, r0 + T), slice(c0, c0 + T))
    rgb = np.stack(
        [
            etirer(refl["B04"][sl], 2, 98),
            etirer(refl["B03"][sl], 2, 98),
            etirer(refl["B02"][sl], 2, 98),
        ],
        2,
    )
    base = (rgb * 255).astype("uint8")

    def sur(masque, couleur):
        a = base.copy()
        m = masque[sl]
        a[m] = (0.35 * a[m] + 0.65 * np.array(couleur)).astype("uint8")
        return a

    vvg = (etirer(db[sl], 2, 98) * 255).astype("uint8")
    vvg = np.stack([vvg] * 3, 2)
    s2o = sur(eau_s2, (255, 0, 0))
    s1o = sur(det, (255, 220, 0))
    ligne1 = np.concatenate([base, vvg], 1)
    ligne2 = np.concatenate([s2o, s1o], 1)
    png(np.concatenate([ligne1, ligne2], 0), f"{V}/vis_{nom}.png", zoom=1)
    x0, y0 = gb.affine * (c0, r0)
    print(
        nom,
        f"fenêtre 4 km en L93 ({x0 / 1000:.1f}, {y0 / 1000:.1f}) km ; S2 crue {int((eau_s2[sl] & dans[sl]).sum() * 0.01)} ha ; S1 détecte {int((det[sl] & dans[sl]).sum() * 0.01)} ha ; faux positifs {int(fp[sl].sum() * 0.01)} ha ; manqués {int(fn[sl].sum() * 0.01)} ha",
        flush=True,
    )
print("terminé")
