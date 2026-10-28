# ruff: noqa
"""V2.0 C2 : validation de la détection de crue de Sentinel-1 sur l'image Sentinel-2 du 2025-02-04 (crue du Lay vers La Bretonnière-la-Claye et Lairoux)."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import pandas as pd, time, datetime as dt, collections

JOUR = dt.date(2025, 2, 4)
dom = gpd.read_parquet(f"{V}/domaine.parquet").set_index("marais").loc["poitevin"].geometry
gb = GeoBox.from_bbox((366000, 6598000, 382000, 6614000), crs="EPSG:2154", resolution=10)
dans_zps = ~geometry_mask([dom], out_shape=gb.shape, transform=gb.affine)
bb = tuple(
    gpd.GeoSeries.from_xy(
        [gb.boundingbox.left, gb.boundingbox.right],
        [gb.boundingbox.bottom, gb.boundingbox.top],
        crs=2154,
    )
    .to_crs(4326)
    .total_bounds
)
t0 = time.time()
print("grille", gb.shape, "px dans le ZPS", int(dans_zps.sum()), flush=True)


def charger(items, bandes, dtype="uint16", nodata=0):
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


def mndwi(items):
    items = [i for i in items if offset(i) is not None]
    ds = charger(items, ["B03", "B11", "SCL"])
    par = {}
    for i in items:
        par.setdefault(np.datetime64(i.datetime.date()), []).append(i)
    off = np.array(
        [
            offset(par[min(par, key=lambda d: abs(d - t.astype("datetime64[D]")))][0])
            for t in ds.time.values
        ],
        "float32",
    )[:, None, None]
    g = np.clip((ds.B03.values.astype("float32") + off) / 1e4, 0, None)
    s = np.clip((ds.B11.values.astype("float32") + off) / 1e4, 0, None)
    v = np.isin(ds.SCL.values, [4, 5, 6, 7]) & (ds.B03.values > 0) & (ds.B11.values > 0)
    return (
        np.where(v, (g - s) / (g + s + 1e-6), np.nan),
        v,
        [str(t)[:10] for t in ds.time.values],
        ds.SCL.values,
    )


s2 = [
    i for i in CL.search(collections=["sentinel-2-l2a"], bbox=bb, datetime=f"{JOUR}/{JOUR}").items()
]
print(
    "S2 le",
    JOUR,
    ":",
    len(s2),
    "scènes, tuiles",
    sorted({i.properties["s2:mgrs_tile"] for i in s2}),
    "nuages",
    [round(i.properties.get("eo:cloud_cover", -1)) for i in s2],
    "baseline",
    sorted({i.properties.get("s2:processing_baseline") for i in s2}),
    flush=True,
)
m_h, v_h, d_h, scl = mndwi(s2)
valide = v_h[0]
print(
    "pixels valides (fenêtre)",
    round(100 * valide.mean()),
    "% ; dans le ZPS",
    round(100 * (valide & dans_zps).sum() / dans_zps.sum()),
    "%",
    "| classes SCL : ",
    {int(k): round(100 * float((scl[0] == k).mean()), 1) for k in (3, 4, 5, 6, 8, 9, 10, 11)},
    flush=True,
)
est = list(
    CL.search(
        collections=["sentinel-2-l2a"],
        bbox=bb,
        datetime="2024-08-01/2024-08-31",
        query={"eo:cloud_cover": {"lt": 60}},
    ).items()
)
m_e, v_e, d_e, _ = mndwi(est)
perm = np.nanmedian(m_e, axis=0) > 0
print(
    "eau permanente S2 (août 2024) :",
    round(perm.sum() * 0.01),
    "ha ;",
    len(d_e),
    "dates",
    f"t={time.time() - t0:.0f}s",
    flush=True,
)
eau_s2 = (m_h[0] > 0) & valide & ~perm
print(
    "crue S2 le 2025-02-04 : fenêtre",
    round(eau_s2.sum() * 0.01),
    "ha sur",
    round(valide.sum() * 0.01),
    "ha valides ; dans le ZPS",
    round((eau_s2 & dans_zps).sum() * 0.01),
    "ha sur",
    round((valide & dans_zps).sum() * 0.01),
    flush=True,
)
# ---- Sentinel-1
s1_ete = list(
    CL.search(collections=["sentinel-1-rtc"], bbox=bb, datetime="2024-07-01/2024-09-30").items()
)
refs = {}


def ref(orb):
    if orb not in refs:
        v = charger(
            [i for i in s1_ete if i.properties["sat:relative_orbit"] == orb],
            ["vv"],
            "float32",
            -32768,
        ).vv.values
        refs[orb] = np.nanmedian(
            np.where(np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan), axis=0
        )
    return refs[orb]


VAR = {
    "VV ≤ -16 seul": (None, -16),
    "VV ≤ -18 seul": (None, -18),
    "Δ ≤ -3 et VV ≤ -14": (-3, -14),
    "Δ ≤ -3 et VV ≤ -16": (-3, -16),
    "Δ ≤ -4 et VV ≤ -16": (-4, -16),
    "Δ ≤ -2 et VV ≤ -16": (-2, -16),
}
s1 = list(
    CL.search(
        collections=["sentinel-1-rtc"],
        bbox=bb,
        datetime=f"{JOUR - dt.timedelta(days=3)}/{JOUR + dt.timedelta(days=3)}",
    ).items()
)
rows = []
for orb in sorted({i.properties["sat:relative_orbit"] for i in s1}):
    its = [i for i in s1 if i.properties["sat:relative_orbit"] == orb]
    v = charger(its, ["vv"], "float32", -32768).vv.values
    for k in range(v.shape[0]):
        x = v[k]
        ok = np.isfinite(x) & (x > 0)
        db = np.where(ok, 10 * np.log10(np.where(x > 0, x, 1)), np.nan)
        r = ref(orb)
        for zone, masque in (("fenêtre", np.ones(gb.shape, bool)), ("ZPS", dans_zps)):
            base = valide & ok & ~perm & np.isfinite(r) & masque
            for nom, (dl, ab) in VAR.items():
                det = (
                    (db < ab)
                    & ((db - r) < dl if dl is not None else True)
                    & (r >= -16 if dl is not None else True)
                )
                tp = int((det & eau_s2 & base).sum())
                fp = int((det & ~eau_s2 & base).sum())
                fn = int((~det & eau_s2 & base).sum())
                rows.append(
                    dict(
                        zone=zone,
                        orbite=orb,
                        date_s1=str(its[0].datetime.date()) if v.shape[0] == 1 else f"{k}",
                        variante=nom,
                        ha_s2=round(float((eau_s2 & base).sum() * 0.01)),
                        ha_s1=round(float((det & base).sum() * 0.01)),
                        precision=tp / max(tp + fp, 1),
                        rappel=tp / max(tp + fn, 1),
                    )
                )
    print(
        "  orbite",
        orb,
        sorted({str(i.datetime.date()) for i in its}),
        f"t={time.time() - t0:.0f}s",
        flush=True,
    )
pd.DataFrame(rows).to_csv(f"{V}/verite_lay.csv", index=False)
print("terminé")
