# ruff: noqa
"""V2.0 marée, corrélation par pixel entre le radar et la hauteur de marée, distances au réseau maritime et à la côte, test par passage. Jetable, hors dépôt de production (voir docs/spikes/07_v2_chiffrage.md, section 2.3)."""

import warnings

warnings.filterwarnings("ignore")
import os
import sys, numpy as np, pandas as pd, geopandas as gpd
from affine import Affine
from rasterio.features import geometry_mask, rasterize
from scipy import ndimage as ndi, stats

S = os.environ.get("V20_SORTIE", "rasters/v2_0")
RESEAU = os.environ.get("V20_RESEAU", "D")  # variante du réseau maritime (m3) : D retenue
MARAIS = sys.argv[1]
ORBS = [int(x) for x in sys.argv[2].split(",")]
SEUIL = float(sys.argv[3]) if len(sys.argv) > 3 else -0.5
dom = gpd.read_parquet(f"{S}/domaine.parquet").set_index("marais").loc[MARAIS].geometry
lm = gpd.read_parquet(f"{S}/limite_terre_mer.parquet")
coast = lm[lm.type_de_limite.isna() & (lm.niveau == "Plus hautes eaux")].geometry
net = gpd.read_parquet(f"{S}/maree/atteint_{RESEAU}.parquet").geometry
rng = np.random.default_rng(0)


def corr(db, h):
    ok = np.isfinite(db) & np.isfinite(h)[:, None, None]
    n = ok.sum(0)
    x = np.where(ok, db, 0).astype("float32")
    hh = np.where(ok, h[:, None, None], 0).astype("float32")
    mx = x.sum(0) / np.maximum(n, 1)
    mh = hh.sum(0) / np.maximum(n, 1)
    dx = np.where(ok, db - mx, 0)
    dh = np.where(ok, h[:, None, None] - mh, 0)
    r = (dx * dh).sum(0) / np.sqrt((dx**2).sum(0) * (dh**2).sum(0) + 1e-9)
    return np.where(n >= 20, r, np.nan), n


for orb in ORBS:
    z = np.load(f"{S}/maree/pile_{MARAIS}_{orb}.npz")
    db = z["db"].astype("float32")
    h = z["h"]
    tr = Affine(*z["transform"])
    shp = tuple(z["shape"])
    dans = geometry_mask([dom], out_shape=shp, transform=tr, invert=True)

    def dist(geoms):
        m = rasterize(
            [(g, 1) for g in geoms if not g.is_empty],
            out_shape=shp,
            transform=tr,
            fill=0,
            all_touched=True,
        ).astype(bool)
        return ndi.distance_transform_edt(~m) * 30

    dN, dC = dist(net), dist(coast)
    r, n = corr(db, h)
    nul = [corr(db, rng.permutation(h))[0] for _ in range(3)]
    nulfrac = np.mean([np.nanmean((x[dans] < SEUIL)) for x in nul])
    ha = 0.09
    print(
        f"\n=== {MARAIS} orbite {orb} : {db.shape[0]} passages, hauteur {np.nanmin(h):.2f}-{np.nanmax(h):.2f} m (écart-type {np.nanstd(h):.2f}), pixels du domaine {int(dans.sum())} ({dans.sum() * ha:.0f} ha)"
    )
    v = dans & np.isfinite(r)
    print(
        f"part des pixels avec r < {SEUIL} : {np.mean(r[v] < SEUIL):.3%} ; hasard (hauteurs permutées) : {nulfrac:.3%} ; r > {-SEUIL} : {np.mean(r[v] > -SEUIL):.3%}"
    )
    tide = v & (r < SEUIL)
    print(
        "surface avec r<seuil (ha) :",
        round(tide.sum() * ha),
        "; médiane de r :",
        round(float(np.nanmedian(r[v])), 3),
    )
    bins = [0, 30, 100, 250, 500, 1000, 2000, 5000, 1e9]
    for nom, d in ((f"réseau maritime {RESEAU}", dN), ("côte", dC)):
        lab = pd.cut(pd.Series(d[v]), bins, include_lowest=True)
        df = pd.DataFrame({"c": lab, "t": tide[v]})
        g = df.groupby("c").t.agg(["size", "sum"])
        g["part"] = (g["sum"] / g["size"]).round(3)
        g["ha_domaine"] = (g["size"] * ha).round()
        g["ha_marée"] = (g["sum"] * ha).round()
        print(f"-- distance au {nom} :")
        print(g[["ha_domaine", "ha_marée", "part"]].to_string())
    print(
        "-- surface de marée restante (ha) après exclusion du réseau {RESEAU} + marge, et surface retirée (ha) :"
    )
    for M in (0, 50, 100, 250, 500, 1000):
        keep = v & (dN > M)
        print(
            f"   marge {M:4d} m : retirée {round((v & ~keep).sum() * ha):6d} ha ; marée restante {round((tide & keep).sum() * ha):5d} ha ; part restante {np.mean(r[keep] < SEUIL):.3%}"
        )
    for D in (500, 1000, 2000):
        keep = v & (dC > D)
        print(
            f"   côte {D:4d} m : retirée {round((v & ~keep).sum() * ha):6d} ha ; marée restante {round((tide & keep).sum() * ha):5d} ha ; part restante {np.mean(r[keep] < SEUIL):.3%}"
        )
    # test par passage : surface « crue » (changement) dans le domaine retenu contre la hauteur de marée
    med = np.nanmedian(db, axis=0)
    wet = (db < -16) & ((db - med) < -3) & np.isfinite(db)
    print("-- corrélation surface détectée par passage / hauteur de marée :")
    for nom, keep in (
        ("tout le domaine", v),
        (f"hors réseau {RESEAU} + 250 m", v & (dN > 250)),
        (f"hors réseau {RESEAU} + 250 m et côte 1 km", v & (dN > 250) & (dC > 1000)),
    ):
        a = wet[:, keep].sum(1) * ha
        ok = np.isfinite(h) & np.isfinite(a)
        if ok.sum() > 5:
            rr, p = stats.pearsonr(a[ok], h[ok])
            print(
                f"   {nom:40s} : r = {rr:+.2f} (p = {p:.2f}), surface moyenne {a[ok].mean():.0f} ha, de {a[ok].min():.0f} à {a[ok].max():.0f}"
            )
    np.savez_compressed(
        f"{S}/maree/r_{MARAIS}_{orb}.npz",
        r=r.astype("float32"),
        n=n.astype("uint8"),
        dN=dN.astype("float32"),
        dC=dC.astype("float32"),
        dans=dans,
    )
