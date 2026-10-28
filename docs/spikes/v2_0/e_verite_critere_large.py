# ruff: noqa
"""V2.0 E : vérité de terrain plus complète (eau libre + prairie inondée) et filtre spatial du radar, contrôle visuel sur 3 fenêtres de 4 km."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import pandas as pd, time, datetime as dt, rasterio, rasterio.shutil
from scipy import ndimage as ndi

CAS = [
    ("breton_2021", (321400, 6660100, 325400, 6664100), dt.date(2021, 1, 8), 103),
    ("poitevin_2021", (374700, 6598200, 378700, 6602200), dt.date(2021, 1, 8), 8),
    ("breton_2024", (322400, 6647100, 326400, 6651100), dt.date(2024, 1, 6), 81),
]


def retry(f):
    for t in range(6):
        try:
            return f()
        except Exception:
            time.sleep(5 * (t + 1))
    raise RuntimeError


def charger(gb, items, bandes, dtype="uint16", nodata=0):
    ds = odc.stac.load(
        items,
        bands=bandes,
        geobox=gb,
        groupby="solar_day",
        chunks={"x": 1024, "y": 1024},
        resampling={"*": "nearest"},
        patch_url=planetary_computer.sign,
        dtype=dtype,
        nodata=nodata,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        return ds.compute()


def png(a, chemin):
    tmp = chemin.replace(".png", ".tif")
    with rasterio.open(
        tmp, "w", driver="GTiff", height=a.shape[0], width=a.shape[1], count=3, dtype="uint8"
    ) as dst:
        dst.write(np.moveaxis(a, 2, 0))
    rasterio.shutil.copy(tmp, chemin, driver="PNG")
    os.remove(tmp)


def etirer(x):
    l, h = np.nanpercentile(x, [2, 98])
    return np.clip((x - l) / (h - l + 1e-9), 0, 1)


for nom, bornes, jour, orb in CAS:
    gb = GeoBox.from_bbox(bornes, crs="EPSG:2154", resolution=10)
    bb = tuple(
        gpd.GeoSeries.from_xy([bornes[0], bornes[2]], [bornes[1], bornes[3]], crs=2154)
        .to_crs(4326)
        .total_bounds
    )
    an = jour.year - 1
    s2 = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-2-l2a"], bbox=bb, datetime=f"{jour}/{jour}"
            ).items()
            if offset(i) is not None
        ]
    )
    ds = charger(gb, s2, ["B02", "B03", "B04", "B08", "B11", "SCL"])
    off = float(offset(s2[0]))
    R = {
        b: np.clip((ds[b].values[0].astype("float32") + off) / 1e4, 0, None)
        for b in ("B02", "B03", "B04", "B08", "B11")
    }
    val = np.isin(ds.SCL.values[0], [4, 5, 6, 7]) & (ds.B03.values[0] > 0) & (ds.B11.values[0] > 0)
    mn = (R["B03"] - R["B11"]) / (R["B03"] + R["B11"] + 1e-6)
    nd = (R["B03"] - R["B08"]) / (R["B03"] + R["B08"] + 1e-6)
    est = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-2-l2a"],
                bbox=bb,
                datetime=f"{an}-08-01/{an}-08-31",
                query={"eo:cloud_cover": {"lt": 60}},
            ).items()
            if offset(i) is not None
        ]
    )
    dse = charger(gb, est, ["B03", "B11", "SCL"])
    g = np.clip((dse.B03.values.astype("float32") + offset(est[0])) / 1e4, 0, None)
    s = np.clip((dse.B11.values.astype("float32") + offset(est[0])) / 1e4, 0, None)
    perm = (
        np.nanmedian(
            np.where(np.isin(dse.SCL.values, [4, 5, 6, 7]), (g - s) / (g + s + 1e-6), np.nan),
            axis=0,
        )
        > 0
    )
    M0 = (mn > 0) & val & ~perm  # eau libre (MNDWI)
    M2 = (
        (R["B08"] < 0.12) & (R["B03"] < 0.15) & val & ~perm
    )  # eau libre ou prairie inondée : proche infrarouge très bas, sans surface claire
    s1 = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-1-rtc"],
                bbox=bb,
                datetime=f"{jour - dt.timedelta(days=3)}/{jour + dt.timedelta(days=3)}",
            ).items()
            if i.properties["sat:relative_orbit"] == orb
        ]
    )
    x = charger(gb, s1, ["vv"], "float32", -32768).vv.values[0]
    ete = retry(
        lambda: [
            i
            for i in CL.search(
                collections=["sentinel-1-rtc"], bbox=bb, datetime=f"{an}-07-01/{an}-09-30"
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
    det = (db < -16) & ((db - ref) < -3) & (ref >= -16) & ok & ~perm  # brut
    dbf = ndi.median_filter(np.where(ok, db, np.nanmedian(db)), size=3)
    reff = ndi.median_filter(np.where(np.isfinite(ref), ref, np.nanmedian(ref)), size=3)
    detf = (dbf < -16) & ((dbf - reff) < -3) & (reff >= -16) & ok & ~perm  # filtré 3 x 3
    lab, n = ndi.label(detf)
    taille = np.bincount(lab.ravel())
    detf = np.isin(lab, np.where(taille >= 10)[0]) & (
        lab > 0
    )  # unité minimale de 10 pixels (0,1 ha)
    ha = lambda m: round(float(m.sum() * 0.01), 1)
    print(
        nom,
        "| S2 MNDWI>0",
        ha(M0),
        "ha ; S2 NIR bas",
        ha(M2),
        "ha ; S1 brut",
        ha(det),
        "ha ; S1 filtré",
        ha(detf),
        "ha",
        flush=True,
    )
    for nm, tr in (("MNDWI", M0), ("NIR bas", M2)):
        for nd_, dm in (("brut", det), ("filtré", detf)):
            tp = (dm & tr).sum()
            fp = (dm & ~tr & val).sum()
            fn = (~dm & tr).sum()
            p = tp / max(tp + fp, 1)
            r = tp / max(tp + fn, 1)
            print(
                f"   vérité {nm:8s} / S1 {nd_:7s} : précision {p:.2f} rappel {r:.2f} F1 {2 * p * r / max(p + r, 1e-9):.2f}"
            )
    base = (np.stack([etirer(R["B04"]), etirer(R["B03"]), etirer(R["B02"])], 2) * 255).astype(
        "uint8"
    )

    def sur(m, c):
        a = base.copy()
        a[m] = (0.35 * a[m] + 0.65 * np.array(c)).astype("uint8")
        return a

    png(
        np.concatenate(
            [
                np.concatenate([base, sur(M0, (255, 0, 0)), sur(M2, (255, 0, 0))], 1),
                np.concatenate(
                    [
                        sur(det, (255, 220, 0)),
                        sur(detf, (255, 220, 0)),
                        sur(detf & M2, (0, 255, 255)),
                    ],
                    1,
                ),
            ],
            0,
        ),
        f"{V}/vis2_{nom}.png",
    )
print("terminé")
