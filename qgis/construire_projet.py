"""Construit le projet QGIS de l'observatoire et ses styles (SPEC §8.3) : `make qgis`.

Exécuté par QGIS en Docker sur la machine qui héberge PostGIS (`make qgis`), sans interface ;
`make qgis` charge ensuite le projet dans PostGIS (`carto.qgis_projects`), d'où les postes
distants l'ouvrent par le tunnel SSH (Projet › Ouvrir depuis › PostgreSQL). Peut aussi être
ouvert et exécuté dans la console Python d'un QGIS de bureau, depuis le dépôt.

Produit, dans le dossier de ce script :
- `secheresse_<slug>.qgz` : couches PostGIS par le service `secheresse_<slug>` (aucun mot de
  passe dans le projet : il vient de pgpass, ou de PGPASSWORD pour `make qgis`) ;
- `styles/*.qml` : styles des couches, réutilisables dans un autre projet.

Tout ce qui est propre au territoire (slug, nom, CRS) et la palette des 7 classes sont lus
dans `config/`. Relancer le script régénère le projet.
"""

from __future__ import annotations

import re
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsDataSourceUri,
    QgsDateTimeRange,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsLayerTreeGroup,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterLayer,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsRendererRange,
    QgsRuleBasedRenderer,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QTime

# --- Emplacement et configuration du territoire ----------------------------------------------


def _dossier_qgis() -> Path:
    try:
        dossier = Path(__file__).resolve().parent
    except NameError:  # code collé dans la console : aucun fichier de référence
        raise SystemExit("Ouvrir qgis/construire_projet.py depuis le dépôt.") from None
    if not (dossier.parent / "config" / "projet.yaml").is_file():
        raise SystemExit(f"config/projet.yaml introuvable à côté de {dossier} (make qgis).")
    return dossier


DOSSIER = _dossier_qgis()
CONFIG = DOSSIER.parent / "config"
PROJET_YAML = (CONFIG / "projet.yaml").read_text(encoding="utf-8")
CLASSES_YAML = (CONFIG / "classes.yaml").read_text(encoding="utf-8")


def _valeur(cle: str) -> str:
    """Valeur d'une clé simple de projet.yaml (lecture sans module yaml, absent de QGIS)."""
    trouve = re.search(rf'^\s*{cle}:\s*"?([^"#\n]+?)"?\s*(#.*)?$', PROJET_YAML, re.MULTILINE)
    if not trouve:
        raise ValueError(f"« {cle} » introuvable dans config/projet.yaml")
    return trouve.group(1).strip()


SLUG = _valeur("slug")
NOM = _valeur("nom")
CRS = _valeur("crs")
FRAICHEUR = _valeur("fraicheur_max_jours")
DEBUT_HISTORIQUE = int(_valeur("historique_debut"))
SERVICE = f"secheresse_{SLUG}"
CLASSES = [
    (int(n), libelle, couleur)
    for n, libelle, couleur in re.findall(
        r'\{classe:\s*(\d+),\s*libelle:\s*"([^"]+)",\s*couleur:\s*"(#[0-9a-fA-F]{6})"\}',
        CLASSES_YAML,
    )
]
if len(CLASSES) != 7:
    raise ValueError("config/classes.yaml : 7 classes avec libellé et couleur attendues")

# --- Couches ---------------------------------------------------------------------------------

POLYGONE = Qgis.WkbType.MultiPolygon
POINT = Qgis.WkbType.Point


def couche_postgis(
    nom: str, schema: str, table: str, cle: str, type_geom: Qgis.WkbType, filtre: str = ""
) -> QgsVectorLayer:
    uri = QgsDataSourceUri(f"service='{SERVICE}'")
    uri.setDataSource(schema, table, "geom", filtre, cle)
    uri.setSrid(CRS.split(":")[1])
    uri.setWkbType(type_geom)
    uri.setParam("checkPrimaryKeyUnicity", "0")  # vues : clé unique par construction
    couche = QgsVectorLayer(uri.uri(False), nom, "postgres")
    if not couche.isValid():
        raise RuntimeError(
            f"Couche « {nom} » ({schema}.{table}) invalide : vérifier le tunnel SSH, le "
            f"service « {SERVICE} » (PGSERVICEFILE) et pgpass, puis que la base est à jour "
            "(make db-rebuild)."
        )
    return couche


def temporelle(couche: QgsVectorLayer) -> None:
    """Visible la semaine de son lundi (`debut`) : [lundi, lundi suivant[."""
    proprietes = couche.temporalProperties()
    proprietes.setIsActive(True)
    proprietes.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
    proprietes.setStartField("debut")
    proprietes.setFixedDuration(7)
    proprietes.setDurationUnits(Qgis.TemporalUnit.Days)
    proprietes.setLimitMode(Qgis.VectorTemporalLimitMode.IncludeBeginExcludeEnd)


# --- Symbologie ------------------------------------------------------------------------------


def remplissage(couleur: str) -> QgsFillSymbol:
    return QgsFillSymbol.createSimple(
        {"color": couleur, "outline_color": "#4d4d4d", "outline_width": "0.26"}
    )


def point(
    couleur: str, creux: bool = False, taille: str = "3.2", forme: str = "circle"
) -> QgsMarkerSymbol:
    """Liseré blanc : un point reste visible sur une zone de la même classe."""
    if creux:  # anneau de couleur sur fond blanc translucide : valeur affichée, hors composite
        proprietes = {"name": forme, "color": "255,255,255,170", "outline_color": couleur,
                      "outline_width": "0.9", "size": taille}  # fmt: skip
    else:
        proprietes = {"name": forme, "color": couleur, "outline_color": "#ffffff",
                      "outline_width": "0.5", "size": taille}  # fmt: skip
    return QgsMarkerSymbol.createSimple(proprietes)


def libelle_classe(n: int, libelle: str) -> str:
    return f"{n} – {libelle}"


def rendu_classes(
    symbole: type[QgsFillSymbol] | type[QgsMarkerSymbol],
) -> QgsCategorizedSymbolRenderer:
    categories = []
    for n, libelle, couleur in CLASSES:
        forme = remplissage(couleur) if symbole is QgsFillSymbol else point(couleur)
        categories.append(QgsRendererCategory(n, forme, libelle_classe(n, libelle)))
    return QgsCategorizedSymbolRenderer("classe", categories)


def rendu_piezometres() -> QgsRuleBasedRenderer:
    """Classe en couleur ; une station hors composite (mesure trop ancienne, D1) en contour."""
    racine = QgsRuleBasedRenderer.Rule(None)
    for titre, filtre, creux in (
        ("Au composite de la semaine", '"dans_composite"', False),
        (f"Hors composite : mesure de plus de {FRAICHEUR} jours", 'NOT "dans_composite"', True),
    ):
        groupe = QgsRuleBasedRenderer.Rule(None, 0, 0, filtre, titre)
        for n, libelle, couleur in CLASSES:
            groupe.appendChild(
                QgsRuleBasedRenderer.Rule(
                    point(couleur, creux), 0, 0, f'"classe" = {n}', libelle_classe(n, libelle)
                )
            )
        racine.appendChild(groupe)
    return QgsRuleBasedRenderer(racine)


def rendu_gradue(
    champ: str, bornes: list[float], couleurs: list[str], unite: str, points: bool
) -> QgsGraduatedSymbolRenderer:
    """Plages de valeurs ; en points, des carrés, pour ne pas confondre avec les classes."""
    plages = []
    for bas, haut, couleur in zip(bornes[:-1], bornes[1:], couleurs, strict=True):
        forme = point(couleur, taille="4", forme="square") if points else remplissage(couleur)
        plages.append(QgsRendererRange(bas, haut, forme, f"{bas:g} à {haut:g} {unite}"))
    return QgsGraduatedSymbolRenderer(champ, plages)


def contour_fin(couche: QgsVectorLayer, couleur: str, epaisseur: str = "0.15") -> None:
    """Contour seul, sans remplissage (rendu à symbole unique, celui d'une couche neuve)."""
    couche.renderer().setSymbol(
        QgsFillSymbol.createSimple(
            {"color": "255,255,255,0", "outline_color": couleur, "outline_width": epaisseur}
        )
    )


def contours_etiquetes(couche: QgsVectorLayer) -> None:
    contour_fin(couche, "#222222", "0.5")
    etiquette = QgsPalLayerSettings()
    etiquette.fieldName = "libelle"
    format_texte = QgsTextFormat()
    format_texte.setSize(8)
    etiquette.setFormat(format_texte)
    couche.setLabeling(QgsVectorLayerSimpleLabeling(etiquette))
    couche.setLabelsEnabled(True)


ONDE = ([0, 10, 30, 50, 75, 100], ["#ffffd4", "#fed98e", "#fe9929", "#d95f0e", "#993404"])
# Remplissage : dégradé de bleus (vide pâle, plein foncé), distinct de la palette des classes
RETENUES = ([0, 20, 40, 60, 80, 110], ["#deebf7", "#9ecae1", "#4292c6", "#2171b5", "#084594"])
OPACITE_ZONES = 0.7  # le fond de carte et les stations restent lisibles sous les zones

# --- Assemblage ------------------------------------------------------------------------------


def ajouter(
    projet: QgsProject, groupe: QgsLayerTreeGroup, couche: QgsVectorLayer | QgsRasterLayer,
    visible: bool = True, style: str | None = None,
) -> None:  # fmt: skip
    projet.addMapLayer(couche, False)
    noeud = groupe.addLayer(couche)
    noeud.setItemVisibilityChecked(visible)
    noeud.setExpanded(False)
    if style and isinstance(couche, QgsVectorLayer):
        (DOSSIER / "styles").mkdir(exist_ok=True)
        couche.saveNamedStyle(str(DOSSIER / "styles" / f"{style}.qml"))


def construire() -> Path:
    projet = QgsProject()
    projet.setCrs(QgsCoordinateReferenceSystem(CRS))
    projet.setTitle(f"Observatoire de la sécheresse – {NOM}")
    racine = projet.layerTreeRoot()

    # Semaine la plus récente
    recente = racine.addGroup("Dernière semaine")
    vue = "v_indice_station"
    piezos = couche_postgis("Piézomètres (IPS)", "carto", vue, "cle", POINT,
                            "\"indice\" = 'ips' AND \"derniere\"")  # fmt: skip
    piezos.setRenderer(rendu_piezometres())
    ajouter(projet, recente, piezos, style="ips_station")
    debits = couche_postgis("Stations hydrométriques (débit)", "carto", vue, "cle", POINT,
                            "\"indice\" = 'debit' AND \"derniere\"")  # fmt: skip
    debits.setRenderer(rendu_classes(QgsMarkerSymbol))
    ajouter(projet, recente, debits, style="classes_station")
    retenues = couche_postgis("Retenues : dernier relevé (% de remplissage)", "carto",
                              "v_retenue", "cle", POINT, '"derniere"')  # fmt: skip
    retenues.setRenderer(rendu_gradue("remplissage_pct", *RETENUES, "%", points=True))
    ajouter(projet, recente, retenues, style="retenues")
    composite = couche_postgis("Indice composite par zone", "carto", "v_composite_zone", "cle",
                               POLYGONE, '"derniere"')  # fmt: skip
    composite.setRenderer(rendu_classes(QgsFillSymbol))
    composite.setOpacity(OPACITE_ZONES)
    ajouter(projet, recente, composite, style="classes_zone")
    for indice, titre in (("spi_3", "SPI 3 mois"), ("ips", "IPS"), ("debit", "Débit")):
        couche = couche_postgis(f"{titre} par zone", "carto", "v_indice_zone", "cle", POLYGONE,
                                f"\"indice\" = '{indice}' AND \"derniere\"")  # fmt: skip
        couche.setRenderer(rendu_classes(QgsFillSymbol))
        couche.setOpacity(OPACITE_ZONES)
        ajouter(projet, recente, couche, visible=False)
    onde = couche_postgis("ONDE : dernière campagne (% sans écoulement)", "carto",
                          "v_onde_zone", "cle", POLYGONE, '"derniere"')  # fmt: skip
    onde.setRenderer(rendu_gradue("pct_sans_ecoulement", *ONDE, "%", points=False))
    onde.setOpacity(OPACITE_ZONES)
    ajouter(projet, recente, onde, visible=False, style="onde")

    # Historique : curseur temporel (Vue › Panneaux › Contrôleur temporel)
    historique = racine.addGroup("Historique (contrôleur temporel)")
    for titre, table, cle_geom, filtre, rendu in (
        ("Composite par zone", "v_composite_zone", POLYGONE, "",
         lambda: rendu_classes(QgsFillSymbol)),
        ("Piézomètres (IPS)", "v_indice_station", POINT, "\"indice\" = 'ips'", rendu_piezometres),
        ("Stations hydrométriques (débit)", "v_indice_station", POINT, "\"indice\" = 'debit'",
         lambda: rendu_classes(QgsMarkerSymbol)),
        ("ONDE (% sans écoulement)", "v_onde_zone", POLYGONE, "",
         lambda: rendu_gradue("pct_sans_ecoulement", *ONDE, "%", points=False)),
        ("Retenues (% de remplissage)", "v_retenue", POINT, "",
         lambda: rendu_gradue("remplissage_pct", *RETENUES, "%", points=True)),
    ):  # fmt: skip
        couche = couche_postgis(f"{titre} – historique", "carto", table, "cle", cle_geom, filtre)
        couche.setRenderer(rendu())
        if cle_geom == POLYGONE:
            couche.setOpacity(OPACITE_ZONES)
        temporelle(couche)
        ajouter(projet, historique, couche, visible=False)
    historique.setItemVisibilityChecked(False)
    historique.setExpanded(False)

    # Référentiels
    referentiels = racine.addGroup("Référentiels")
    zones = couche_postgis("Zones", "ref", "zone", "zone_id", POLYGONE)
    contours_etiquetes(zones)
    ajouter(projet, referentiels, zones, style="zones_contour")
    stations = couche_postgis("Stations (toutes sources)", "ref", "station", "station_id", POINT)
    stations.setRenderer(
        QgsCategorizedSymbolRenderer(
            "source",
            [
                QgsRendererCategory(source, point(couleur, taille="2.4"), titre)
                for source, couleur, titre in (
                    ("piezo", "#6a3d9a", "Piézomètre"),
                    ("hydro", "#1f78b4", "Station hydrométrique"),
                    ("onde", "#33a02c", "Station ONDE"),
                    ("retenue", "#e31a1c", "Retenue"),
                )
            ],
        )
    )
    ajouter(projet, referentiels, stations, visible=False)
    communes = couche_postgis("Communes", "ref", "commune", "code_insee", POLYGONE)
    contour_fin(communes, "#9e9e9e")
    ajouter(projet, referentiels, communes, visible=False)
    mailles = couche_postgis("Mailles SIM (8 km)", "ref", "maille_safran", "maille_id",
                             Qgis.WkbType.Polygon)  # fmt: skip
    contour_fin(mailles, "#1f78b4")
    ajouter(projet, referentiels, mailles, visible=False)
    referentiels.setExpanded(False)

    # Fond
    osm = QgsRasterLayer(
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmin=0&zmax=19",
        "OpenStreetMap",
        "wms",
    )
    ajouter(projet, racine.addGroup("Fond"), osm)

    # Contrôleur temporel : de la première semaine calculée à aujourd'hui, pas d'une semaine
    temps = projet.timeSettings()
    temps.setTemporalRange(
        QgsDateTimeRange(
            QDateTime(QDate(DEBUT_HISTORIQUE, 1, 1), QTime(0, 0)),
            QDateTime(QDate.currentDate(), QTime(0, 0)),
        )
    )
    temps.setTimeStep(1)
    temps.setTimeStepUnit(Qgis.TemporalUnit.Weeks)

    projet.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(zones.extent(), zones.crs()))
    chemin = DOSSIER / f"secheresse_{SLUG}.qgz"
    if not projet.write(str(chemin)):
        raise RuntimeError(f"Écriture impossible : {chemin}")
    return chemin


def principal() -> None:
    application = None
    if QgsApplication.instance() is None:  # hors de QGIS (make qgis) : application sans interface
        QgsApplication.setPrefixPath("/usr", True)
        application = QgsApplication([], False)
        application.initQgis()
    try:
        print(f"Projet écrit : {construire()}")
    finally:
        if application is not None:
            application.exitQgis()


principal()
