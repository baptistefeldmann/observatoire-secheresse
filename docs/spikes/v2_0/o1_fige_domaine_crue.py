# ruff: noqa
"""V2.1 -> V2.2 : fige le domaine de la surface de crue (variante D de la marée, marge de 250 m, pixels corrélés à la marée, forêt et cordons dunaires retirés, eau permanente de Sentinel-1 réunie aux surfaces permanentes de la BD TOPO) en rasters de 10 m. Les fichiers du spike (masques de marée sur 30 m, masque d'eau permanente, BD TOPO, couche EPMP) ne sont plus nécessaires ensuite : la production lit seulement `data/satellite/domaine_crue_<marais>.tif` et `rasters/crue/regimes_<marais>.tif`. Jetable (voir docs/spikes/07_v2_chiffrage.md, sections 2.3 et 3.9, et docs/architecture_v2.md, section 7.2). Variables : V20_SORTIE (défaut rasters/v2_0) ; V20_FICHIERS (dossier des fichiers temporaires du spike, obligatoire)."""

import os, shutil
from pathlib import Path
import numpy as np, geopandas as gpd
from affine import Affine
from odc.geo.geobox import GeoBox
from rasterio.features import geometry_mask, rasterize

from pipeline.config import charger_config
from pipeline.raster.classes import ecrire_classes
from pipeline.raster.grille import Grille

F = os.environ["V20_FICHIERS"]  # scratchpad du spike : v20/, maree/, sortie/, epmp_grandes_entites/
config = charger_config()
slug = config.projet.territoire.slug
CLES = {
    "poitevin": "marais_poitevin",
    "breton": "marais_breton",
}  # clé du spike -> identifiant de config
dom = gpd.read_parquet(f"{F}/v20/domaine.parquet").set_index("marais")
hydro = gpd.read_parquet(f"{F}/v20/surface_hydro.parquet")
hydro = hydro[
    hydro.persistance == "Permanent"
]  # les surfaces « intermittentes » sont les prairies inondées : pas masquées
epmp = gpd.read_file(f"{F}/epmp_grandes_entites/grandes_entites.gpkg").to_crs(2154)
REGIMES = {
    "Marais mouillés": 1,
    "Marais intermédiaires": 2,
    "Marais desséchés": 3,
    "Cordons dunaires": 4,
    "Fonds de vallée humide": 5,
    "Terres hautes": 6,
    "Schorre (prés salés)": 7,
    "Slikke (vasières)": 8,
}
os.makedirs("data/satellite", exist_ok=True)
os.makedirs("rasters/crue/sources", exist_ok=True)
shutil.copy(
    f"{F}/epmp_grandes_entites/grandes_entites.gpkg",
    "rasters/crue/sources/epmp_grandes_entites.gpkg",
)

for cle, ident in CLES.items():
    geom = dom.loc[cle].geometry
    gb = GeoBox.from_bbox(geom.bounds, crs="EPSG:2154", resolution=10)
    h, w = gb.shape
    grille = Grille(gb.affine.c, gb.affine.f, w, h, 10.0, "EPSG:2154")
    dans = ~geometry_mask([geom], out_shape=gb.shape, transform=gb.affine)
    # domaine de la marée (grille de 30 m du spike) ramené sur la grille de 10 m, par les centres de pixels
    z = np.load(f"{F}/maree/final_{cle}.npz")
    t30 = Affine(*z["transform"])
    ys = grille.ymax - (np.arange(h) + 0.5) * 10
    xs = grille.xmin + (np.arange(w) + 0.5) * 10
    r = np.floor((t30.f - ys) / 30).astype(int)
    c = np.floor((xs - t30.c) / 30).astype(int)
    f30 = z["final_crue"]
    ok_r, ok_c = (r >= 0) & (r < f30.shape[0]), (c >= 0) & (c < f30.shape[1])
    final = np.zeros((h, w), bool)
    final[np.ix_(ok_r, ok_c)] = f30[np.ix_(r[ok_r], c[ok_c])]
    final &= dans
    m_s1 = np.load(f"{F}/sortie/masque_eau_permanente_{cle}.npz")["masque"]
    assert m_s1.shape == (h, w), (m_s1.shape, (h, w))
    hh = hydro[hydro.intersects(geom)]
    m_h = rasterize(
        [(g, 1) for g in hh.geometry if not g.is_empty],
        out_shape=(h, w),
        transform=gb.affine,
        fill=0,
    ).astype(bool)
    perm = m_s1 | m_h
    code = np.zeros((h, w), np.uint8)
    code[final & ~perm] = 1  # domaine mesuré
    code[final & perm] = 2  # eau permanente : dans le domaine de la marée, retirée de la somme
    ha = lambda m: float(m.sum() * 0.01)
    print(
        f"{ident} : grille {h} x {w} ; domaine de crue (avant eau permanente) {ha(final):.0f} ha "
        f"({float(f30.sum() * 0.09):.0f} ha sur 30 m) ; eau permanente dedans {ha(final & perm):.0f} ha "
        f"(S1 {ha(final & m_s1):.0f}, BD TOPO {ha(final & m_h):.0f}) ; surface mesurée {ha(code == 1):.0f} ha",
        flush=True,
    )
    ecrire_classes(
        Path(f"data/satellite/domaine_crue_{ident}.tif"),
        code,
        grille,
        255,
        {
            "codes": "0 hors domaine, 1 domaine mesuré, 2 eau permanente retirée",
            "marais": ident,
            "maree": "variante D, marge 250 m, pixels r<-0.5 +30 m, figé 2022-2025 (grille 30 m ramenée à 10 m)",
            "retire": "foret (BD Foret V2), cordons dunaires (EPMP), marais salants, estran",
            "eau_permanente": "Sentinel-1 orbite 81 juillet-septembre 2015-2025 (part 0.5, -16 dB) + BD TOPO Permanent sans marge",
            "fige_le": "2026-11",
        },
    )
    if cle == "poitevin":  # régimes de l'EPMP (licence à demander, Q17) : hors Git et hors DVC
        reg = np.zeros((h, w), np.uint8)
        for lib, v in REGIMES.items():
            gg = epmp[epmp.libelle == lib].geometry
            reg[
                rasterize(
                    [(g, v) for g in gg if not g.is_empty],
                    out_shape=(h, w),
                    transform=gb.affine,
                    fill=0,
                ).astype(bool)
            ] = v
        for lib, v in REGIMES.items():
            print(
                f"   régime {lib:<26} dans le domaine mesuré : {ha((code == 1) & (reg == v)):8.0f} ha"
            )
        print(
            f"   non classé                              : {ha((code == 1) & (reg == 0)):8.0f} ha"
        )
        ecrire_classes(
            Path(f"rasters/crue/regimes_{ident}.tif"),
            reg,
            grille,
            255,
            {
                "codes": "; ".join(f"{v} {k}" for k, v in REGIMES.items()) + " ; 0 non classé",
                "source": "EPMP grandes entités (licence à demander)",
            },
        )
print("terminé")
