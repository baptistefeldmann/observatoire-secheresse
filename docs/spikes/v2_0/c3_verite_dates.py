# ruff: noqa
"""V2.0 C3 : validation de la détection de crue de Sentinel-1 sur 6 dates de crue claires de Sentinel-2 (indiquées par l'utilisateur),
Marais poitevin (zone du déversoir du Lay séparée du reste) et Marais breton."""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s2_common import *  # noqa: F403
import pandas as pd, time, datetime as dt
from scipy import ndimage as ndi

DATES = [
    dt.date(2020, 2, 6),
    dt.date(2020, 12, 12),
    dt.date(2021, 1, 8),
    dt.date(2022, 1, 11),
    dt.date(2024, 1, 6),
    dt.date(2024, 3, 3),
]
dom = gpd.read_parquet(f"{V}/domaine.parquet").set_index("marais")
com = gpd.read_parquet("data/referentiels/communes.parquet")
dev_noms = ["La Bretonnière-la-Claye", "Lairoux", "Curzon", "La Couture"]
dev = com[com.nom.isin(dev_noms)]
print("communes du déversoir trouvées :", sorted(dev.nom), flush=True)
dev_geom = dev.geometry.union_all()


def retry(f, *a, **k):
    for t in range(12):
        try:
            return f(*a, **k)
        except Exception as e:
            print("   (reprise)", type(e).__name__, flush=True)
            time.sleep(min(10 * (t + 1), 90))
    raise RuntimeError("échec STAC")


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


def mndwi(gb, items):
    items = [i for i in items if offset(i) is not None]
    ds = charger(gb, items, ["B03", "B11", "SCL"])
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
    return np.where(v, (g - s) / (g + s + 1e-6), np.nan), v


VARF = {
    "Δ ≤ -2 et VV ≤ -16 + filtre": (-2, -16),
    "Δ ≤ -3 et VV ≤ -16 + filtre": (-3, -16),
    "Δ ≤ -4 et VV ≤ -16 + filtre": (-4, -16),
    "VV ≤ -16 seul + filtre": (None, -16),
}


def filtre(db, ok):
    return ndi.median_filter(np.where(ok, db, np.nanmedian(db)), size=3)


def mmu(det, n=10):
    lab, _ = ndi.label(det)
    taille = np.bincount(lab.ravel())
    return np.isin(lab, np.where(taille >= n)[0]) & (lab > 0)


VAR = {
    "VV ≤ -16 seul": (None, -16),
    "VV ≤ -18 seul": (None, -18),
    "Δ ≤ -3 et VV ≤ -14": (-3, -14),
    "Δ ≤ -3 et VV ≤ -16": (-3, -16),
    "Δ ≤ -4 et VV ≤ -16": (-4, -16),
    "Δ ≤ -2 et VV ≤ -16": (-2, -16),
}
rows = []
t0 = time.time()
perm_c, ref_c = {}, {}
for marais in ("poitevin", "breton"):
    geom = dom.loc[marais].geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    zones = {marais: dans}
    if marais == "poitevin":
        dv = (
            ~geometry_mask([dev_geom.intersection(geom)], out_shape=gb.shape, transform=gb.affine)
            & dans
        )
        zones = {"poitevin_deversoir": dv, "poitevin_reste": dans & ~dv}
    print(marais, {z: f"{m.sum() * 0.01:.0f} ha" for z, m in zones.items()}, flush=True)
    bb = tuple(gpd.GeoSeries([geom], crs=2154).to_crs(4326).total_bounds)
    for jour in DATES:
        an_ref = jour.year - 1 if jour.month <= 6 else jour.year
        s2 = retry(
            lambda: list(
                CL.search(
                    collections=["sentinel-2-l2a"], bbox=bb, datetime=f"{jour}/{jour}"
                ).items()
            )
        )
        m_h, v_h = mndwi(gb, s2)
        valide = v_h[0]
        if (marais, an_ref) not in perm_c:
            est = retry(
                lambda: list(
                    CL.search(
                        collections=["sentinel-2-l2a"],
                        bbox=bb,
                        datetime=f"{an_ref}-08-01/{an_ref}-08-31",
                        query={"eo:cloud_cover": {"lt": 60}},
                    ).items()
                )
            )
            m_e, _ = mndwi(gb, est)
            perm_c[(marais, an_ref)] = np.nanmedian(m_e, axis=0) > 0
        perm = perm_c[(marais, an_ref)]
        eau_s2 = (m_h[0] > 0) & valide & ~perm
        info = {
            z: (
                round(float((valide & m).sum() / m.sum()) * 100),
                round(float((eau_s2 & m).sum() * 0.01)),
            )
            for z, m in zones.items()
        }
        print(
            jour, marais, "S2 valide % / crue ha :", info, f"t={time.time() - t0:.0f}s", flush=True
        )
        s1 = retry(
            lambda: list(
                CL.search(
                    collections=["sentinel-1-rtc"],
                    bbox=bb,
                    datetime=f"{jour - dt.timedelta(days=3)}/{jour + dt.timedelta(days=3)}",
                ).items()
            )
        )
        for orb in sorted({i.properties["sat:relative_orbit"] for i in s1} - {132}):
            if (marais, an_ref, orb) not in ref_c:
                ete = retry(
                    lambda: list(
                        CL.search(
                            collections=["sentinel-1-rtc"],
                            bbox=bb,
                            datetime=f"{an_ref}-07-01/{an_ref}-09-30",
                        ).items()
                    )
                )
                v = charger(
                    gb,
                    [i for i in ete if i.properties["sat:relative_orbit"] == orb],
                    ["vv"],
                    "float32",
                    -32768,
                ).vv.values
                ref_c[(marais, an_ref, orb)] = np.nanmedian(
                    np.where(
                        np.isfinite(v) & (v > 0), 10 * np.log10(np.where(v > 0, v, 1)), np.nan
                    ),
                    axis=0,
                )
            r = ref_c[(marais, an_ref, orb)]
            its = [i for i in s1 if i.properties["sat:relative_orbit"] == orb]
            v = charger(gb, its, ["vv"], "float32", -32768).vv.values
            for k in range(v.shape[0]):
                x = v[k]
                ok = np.isfinite(x) & (x > 0)
                db = np.where(ok, 10 * np.log10(np.where(x > 0, x, 1)), np.nan)
                dbf = filtre(db, ok)
                rf = ndi.median_filter(np.where(np.isfinite(r), r, np.nanmedian(r)), size=3)
                for z, m in zones.items():
                    base = valide & ok & ~perm & np.isfinite(r) & m
                    for nom, (dl, ab) in [*VAR.items(), *VARF.items()]:
                        if nom in VARF:
                            det = mmu(
                                (dbf < ab)
                                & ((dbf - rf) < dl if dl is not None else True)
                                & (rf >= -16 if dl is not None else True)
                                & ok
                                & ~perm
                            )
                        else:
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
                                date_s2=str(jour),
                                zone=z,
                                orbite=orb,
                                date_s1=str(ds_date)
                                if (ds_date := str(its[min(k, len(its) - 1)].datetime.date()))
                                else "",
                                variante=nom,
                                valide_pct=round(float(base.sum() / m.sum()) * 100),
                                ha_s2=round(float((eau_s2 & base).sum() * 0.01)),
                                ha_s1=round(float((det & base).sum() * 0.01)),
                                precision=tp / max(tp + fp, 1),
                                rappel=tp / max(tp + fn, 1),
                            )
                        )
            print(
                "   orbite",
                orb,
                sorted({str(i.datetime.date()) for i in its}),
                f"t={time.time() - t0:.0f}s",
                flush=True,
            )
        pd.DataFrame(rows).to_csv(f"{V}/verite_dates_filtre.csv", index=False)
print("terminé")
