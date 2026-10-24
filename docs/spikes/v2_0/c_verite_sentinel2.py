# ruff: noqa
"""V2.0 C : vérité de terrain par Sentinel-2 (images claires, janvier-février 2024) pour juger la détection de crue par Sentinel-1
(S2 sert à valider uniquement). Marais poitevin."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import pandas as pd, time, datetime as dt, collections

dom = gpd.read_parquet(f"{V}/domaine.parquet").set_index("marais")
geom = dom.loc["poitevin"].geometry
gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
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
print("grille", gb.shape, "px domaine", int(dans.sum()), flush=True)


def charger(items, bandes, dtype="uint16", nodata=0, **kw):
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
        **kw,
    )
    with dask.config.set(scheduler="threads", num_workers=8):
        return ds.compute()


# ---- 1. choix des dates S2 claires
cand = list(
    CL.search(
        collections=["sentinel-2-l2a"],
        bbox=bb,
        datetime="2024-01-01/2024-02-29",
        query={"eo:cloud_cover": {"lt": 40}},
    ).items()
)
par_jour = collections.defaultdict(list)
for i in cand:
    par_jour[i.datetime.date()].append(i)
quals = []
for jour, its in sorted(par_jour.items()):
    ds = charger(its, ["SCL"])
    scl = ds.SCL.isel(time=0).values
    ok = np.isin(scl, [4, 5, 6, 7]) & dans
    quals.append((float(ok.sum() / dans.sum()), jour))
    print(" ", jour, f"valide {quals[-1][0]:.2f}", flush=True)
choix = sorted([q for q in quals if q[0] >= 0.6], reverse=True)[:3]
print("dates S2 retenues :", choix, f"t={time.time() - t0:.0f}s", flush=True)
# ---- 2. eau permanente S2 (août 2024, MNDWI médian > 0)
est = list(
    CL.search(
        collections=["sentinel-2-l2a"],
        bbox=bb,
        datetime="2024-08-01/2024-08-31",
        query={"eo:cloud_cover": {"lt": 60}},
    ).items()
)
est = [i for i in est if offset(i) is not None]
ds, meta = cube(est, gb, ("B03", "B11", "SCL")) if False else (None, None)


def mndwi_cube(items):
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
    g = (ds.B03.values.astype("float32") + off) / 1e4
    s = (ds.B11.values.astype("float32") + off) / 1e4
    v = np.isin(ds.SCL.values, [4, 5, 6, 7]) & (ds.B03.values > 0) & (ds.B11.values > 0)
    return (
        np.where(
            v,
            (np.clip(g, 0, None) - np.clip(s, 0, None))
            / (np.clip(g, 0, None) + np.clip(s, 0, None) + 1e-6),
            np.nan,
        ),
        v,
        [str(t)[:10] for t in ds.time.values],
    )


m_e, v_e, d_e = mndwi_cube(est)
perm = (np.nanmedian(m_e, axis=0) > 0) & dans
print(
    "eau permanente S2 (août 2024) :",
    round(perm.sum() * 0.01),
    "ha ;",
    len(d_e),
    "dates",
    f"t={time.time() - t0:.0f}s",
    flush=True,
)
# ---- 3. S2 hiver : surface d'eau hors permanente ; S1 : détection par changement, comparaison pixel à pixel
s1_ete = list(
    CL.search(collections=["sentinel-1-rtc"], bbox=bb, datetime="2024-07-01/2024-09-30").items()
)
refs = {}


def ref_orbite(orb):
    if orb not in refs:
        its = [i for i in s1_ete if i.properties["sat:relative_orbit"] == orb]
        v = charger(its, ["vv"], dtype="float32", nodata=-32768).vv.values
        refs[orb] = np.nanmedian(
            np.where(np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan), axis=0
        )
    return refs[orb]


VARIANTES = {
    "VV ≤ -16 dB seul": (None, -16),
    "VV ≤ -18 dB seul": (None, -18),
    "Δ ≤ -3 dB et VV ≤ -14": (-3, -14),
    "Δ ≤ -3 dB et VV ≤ -16": (-3, -16),
    "Δ ≤ -4 dB et VV ≤ -14": (-4, -14),
    "Δ ≤ -4 dB et VV ≤ -16": (-4, -16),
}
rows = []
for q, jour in choix:
    its = [i for i in par_jour[jour] if offset(i) is not None]
    m_h, v_h, d_h = mndwi_cube(its)
    eau_s2 = (m_h[0] > 0) & v_h[0] & dans & ~perm
    valide = v_h[0] & dans
    print(
        jour,
        "S2 : crue (hors permanente)",
        round(eau_s2.sum() * 0.01),
        "ha sur",
        round(valide.sum() * 0.01),
        "ha valides",
        flush=True,
    )
    s1 = list(
        CL.search(
            collections=["sentinel-1-rtc"],
            bbox=bb,
            datetime=f"{jour - dt.timedelta(days=2)}/{jour + dt.timedelta(days=2)}",
        ).items()
    )
    for orb in sorted({i.properties["sat:relative_orbit"] for i in s1}):
        its1 = [i for i in s1 if i.properties["sat:relative_orbit"] == orb]
        v = charger(its1, ["vv"], dtype="float32", nodata=-32768).vv.values[0]
        ok = np.isfinite(v) & (v > 0)
        db = np.where(ok, 10 * np.log10(np.where(v > 0, v, 1)), np.nan)
        ref = ref_orbite(orb)
        base = valide & ok & ~perm & np.isfinite(ref)
        for nom, (dl, ab) in VARIANTES.items():
            det = (
                (db < ab)
                & ((db - ref) < dl if dl is not None else True)
                & (ref >= -16 if dl is not None else True)
            )
            tp = int((det & eau_s2 & base).sum())
            fp = int((det & ~eau_s2 & base).sum())
            fn = int((~det & eau_s2 & base).sum())
            rows.append(
                dict(
                    s2=str(jour),
                    orbite=orb,
                    date_s1=str(its1[0].datetime.date()),
                    variante=nom,
                    ha_s2=round(float((eau_s2 & base).sum() * 0.01)),
                    ha_s1=round(float((det & base).sum() * 0.01)),
                    precision=tp / max(tp + fp, 1),
                    rappel=tp / max(tp + fn, 1),
                )
            )
        print("  S1 orbite", orb, its1[0].datetime.date(), f"t={time.time() - t0:.0f}s", flush=True)
pd.DataFrame(rows).to_csv(f"{V}/verite.csv", index=False)
print("terminé")
