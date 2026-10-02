"""Chargement et validation de la configuration (`config/*.yaml`) et des variables d'environnement.

Toute constante métier (département, seuils, pondérations, périodes) vient d'ici.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pyproj import CRS
from pyproj.exceptions import CRSError

DOSSIER_CONFIG_DEFAUT = Path("config")
VARIABLE_DOSSIER_CONFIG = "SECHERESSE_CONFIG"

# ONDE n'entre pas dans le composite en V1 (docs/methodologie.md, D3) : affiché seul.
Composante = Literal["spi_3", "ips", "debit"]


class _Modele(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- projet.yaml -------------------------------------------------------------


class Territoire(_Modele):
    code_departement: str = Field(pattern=r"^(\d{2}|2A|2B|97\d)$")
    nom: str
    slug: str = Field(pattern=r"^[a-z0-9_]+$")


class Emprise(_Modele):
    tampon_m: float = Field(ge=0)


class Periode(_Modele):
    debut: int
    fin: int
    annees_min: int | None = Field(default=None, ge=1)
    annees_min_apres_rupture: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _verifier_bornes(self) -> Periode:
        if self.debut > self.fin:
            raise ValueError(f"début ({self.debut}) postérieur à la fin ({self.fin})")
        if self.annees_min is not None and self.annees_min > self.fin - self.debut + 1:
            raise ValueError("annees_min dépasse la longueur de la période")
        return self


class PeriodesReference(_Modele):
    hydro_meteo: Periode
    sentinel2: Periode


class Ingestion(_Modele):
    fenetre_reingestion_jours: int = Field(ge=0)
    piezo_inactif_apres_jours: int = Field(ge=1)


class Chemins(_Modele):
    data: Path
    rasters: Path
    rapports: Path


class Controles(_Modele):
    pluie_max_mm_jour: float = Field(gt=0)
    remplissage_max: float = Field(gt=0)


class Hebdo(_Modele):
    branche: str = Field(min_length=1)
    remote_git: str = Field(min_length=1)
    controles: Controles


class ParametresIps(_Modele):
    fraicheur_max_jours: int = Field(ge=1)
    jours_min_mois: int = Field(ge=1, le=31)


class ParametresDebit(_Modele):
    jours_min_q7: int = Field(ge=1, le=7)
    demi_fenetre_jours: int = Field(ge=0)
    part_min_fenetre: float = Field(gt=0, le=1)


class ParametresRuptures(_Modele):
    seuil_p: float = Field(gt=0, lt=1)
    mois_min_annee: int = Field(ge=1, le=12)
    jours_min_annee: int = Field(ge=1, le=366)


class ParametresSpi(_Modele):
    fenetres_jours: dict[str, int]

    @field_validator("fenetres_jours")
    @classmethod
    def _verifier_fenetres(cls, valeur: dict[str, int]) -> dict[str, int]:
        if "spi_3" not in valeur:
            raise ValueError("spi_3 est requis : c'est la composante SPI du composite")
        if any(j < 1 for j in valeur.values()):
            raise ValueError("fenêtre SPI de moins d'un jour")
        return valeur


class Indices(_Modele):
    version_methodo: str = Field(min_length=1)
    historique_debut: int
    ips: ParametresIps
    debit: ParametresDebit
    ruptures: ParametresRuptures
    spi: ParametresSpi


class Projet(_Modele):
    territoire: Territoire
    crs: str
    emprise: Emprise
    periode_reference: PeriodesReference
    ingestion: Ingestion
    indices: Indices
    hebdo: Hebdo
    chemins: Chemins

    @field_validator("crs")
    @classmethod
    def _verifier_crs(cls, valeur: str) -> str:
        try:
            crs = CRS.from_user_input(valeur)
        except CRSError as exc:
            raise ValueError(f"CRS inconnu : {valeur}") from exc
        if not crs.is_projected:
            raise ValueError(f"le CRS de calcul doit être projeté (mètres) : {valeur}")
        return valeur


# --- classes.yaml ------------------------------------------------------------


class Classe(_Modele):
    classe: int
    libelle: str


class Classes(_Modele):
    seuils: list[float]
    classes: list[Classe]

    @model_validator(mode="after")
    def _verifier_coherence(self) -> Classes:
        if self.seuils != sorted(self.seuils) or len(set(self.seuils)) != len(self.seuils):
            raise ValueError("les seuils doivent être strictement croissants")
        if len(self.classes) != len(self.seuils) + 1:
            raise ValueError("il faut exactement une classe de plus que de seuils")
        if [c.classe for c in self.classes] != list(range(1, len(self.classes) + 1)):
            raise ValueError("les classes doivent être numérotées 1, 2, ... n dans l'ordre")
        return self


# --- zones.yaml --------------------------------------------------------------


class Zone(_Modele):
    zone_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    libelle: str
    type_zone: Literal["hydrogeol", "alerte"]
    masses_eau: list[str] = Field(min_length=1)  # codes SANDRE EDL 2019 (CdEuMasseDEau)
    zones_alerte: list[int] = []  # codes SANDRE CdZAS ; vide = pas de croisement
    ponderations: dict[Composante, float]

    @field_validator("ponderations")
    @classmethod
    def _verifier_ponderations(cls, valeur: dict[Composante, float]) -> dict[Composante, float]:
        if any(p < 0 for p in valeur.values()):
            raise ValueError("pondération négative")
        total = sum(valeur.values())
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(f"les pondérations doivent sommer à 1 (somme = {total})")
        return valeur


class Zonage(_Modele):
    fragment_max_km2: float = Field(gt=0)
    definitions: dict[str, Any] = {}  # ancres YAML, ignorées
    zones: list[Zone] = Field(min_length=1)

    @field_validator("zones")
    @classmethod
    def _verifier_unicite(cls, valeur: list[Zone]) -> list[Zone]:
        ids = [z.zone_id for z in valeur]
        doublons = sorted({i for i in ids if ids.count(i) > 1})
        if doublons:
            raise ValueError(f"zone_id en double : {', '.join(doublons)}")
        return valeur


# --- stations.yaml (facultatif) ----------------------------------------------


class RaccordementHydro(_Modele):
    """Stations successives d'un même site, fusionnées en une seule série."""

    site: str
    libelle: str
    stations: list[str] = Field(min_length=2)  # priorité décroissante
    verification: str


class ChampsRetenues(_Modele):
    retenue: str
    date: str
    capacite_m3: str
    volume_m3: str
    longitude: str
    latitude: str


class SourceRetenues(_Modele):
    """Table ArcGIS propre au territoire : une ligne par retenue et par relevé."""

    table_arcgis: str
    champs: ChampsRetenues
    alias_repli: dict[str, str] = {}


class Rupture(_Modele):
    """Station au fonctionnement modifié : référence limitée aux années à partir de `annee`."""

    station: str  # station_id, ex. « piezo:05068X0028/SP010 »
    annee: int
    motif: str


class Stations(_Modele):
    raccordements_hydro: list[RaccordementHydro] = []
    ruptures: list[Rupture] = []
    retenues: SourceRetenues | None = None

    @field_validator("ruptures")
    @classmethod
    def _verifier_ruptures(cls, valeur: list[Rupture]) -> list[Rupture]:
        ids = [r.station for r in valeur]
        doublons = sorted({i for i in ids if ids.count(i) > 1})
        if doublons:
            raise ValueError(f"station listée deux fois dans les ruptures : {', '.join(doublons)}")
        return valeur

    @field_validator("raccordements_hydro")
    @classmethod
    def _verifier_unicite(cls, valeur: list[RaccordementHydro]) -> list[RaccordementHydro]:
        codes = [c for r in valeur for c in r.stations]
        doublons = sorted({c for c in codes if codes.count(c) > 1})
        if doublons:
            liste = ", ".join(doublons)
            raise ValueError(f"station présente dans plusieurs raccordements : {liste}")
        return valeur


# --- sources.yaml ------------------------------------------------------------


class HubEau(_Modele):
    piezometrie: str
    hydrometrie: str
    ecoulement: str


class Sim(_Modele):
    api_datagouv: str
    jeu_datagouv: str
    crs_grille: str
    unite_coordonnees_m: float = Field(gt=0)
    pas_grille_m: float = Field(gt=0)


class Sentinel2(_Modele):
    stac: str
    collection: str
    nuages_max_scene_pct: float = Field(ge=0, le=100)
    scl_valides: list[int] = Field(min_length=1)
    resolution_m: float = Field(gt=0)
    offset_boa: float
    baseline_offset: str
    facteur_echelle: int = Field(gt=0)

    @field_validator("scl_valides")
    @classmethod
    def _verifier_scl(cls, valeur: list[int]) -> list[int]:
        if any(not 0 <= c <= 11 for c in valeur):
            raise ValueError("les classes SCL valent de 0 à 11")
        return valeur


class Http(_Modele):
    timeout_s: float = Field(gt=0)
    tentatives: int = Field(ge=1)


class CoucheMassesEau(_Modele):
    wfs: str
    couche: str
    couche_noms: str
    horizon: int


class CoucheZonesAlerte(_Modele):
    wfs: str
    couche: str
    statut: str


class RetenuesNational(_Modele):
    wfs: str
    couche: str


class Sandre(_Modele):
    masses_eau: CoucheMassesEau
    zones_alerte: CoucheZonesAlerte


class Sources(_Modele):
    hubeau: HubEau
    geo_api: str
    sandre: Sandre
    retenues_national: RetenuesNational
    sim: Sim
    sentinel2: Sentinel2
    http: Http


# --- Ensemble ----------------------------------------------------------------


class Config(_Modele):
    projet: Projet
    classes: Classes
    zonage: Zonage
    stations: Stations
    sources: Sources


def _lire_yaml(chemin: Path) -> object:
    if not chemin.is_file():
        raise FileNotFoundError(f"fichier de configuration manquant : {chemin}")
    with chemin.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def charger_config(dossier: Path | None = None) -> Config:
    """Charge et valide les fichiers de `dossier` (par défaut `$SECHERESSE_CONFIG` ou `config/`)."""
    if dossier is None:
        dossier = Path(os.environ.get(VARIABLE_DOSSIER_CONFIG, DOSSIER_CONFIG_DEFAUT))
    fichier_stations = dossier / "stations.yaml"
    return Config(
        projet=Projet.model_validate(_lire_yaml(dossier / "projet.yaml")),
        classes=Classes.model_validate(_lire_yaml(dossier / "classes.yaml")),
        zonage=Zonage.model_validate(_lire_yaml(dossier / "zones.yaml")),
        stations=(
            Stations.model_validate(_lire_yaml(fichier_stations))
            if fichier_stations.is_file()
            else Stations()
        ),
        sources=Sources.model_validate(_lire_yaml(dossier / "sources.yaml")),
    )


# --- Variables d'environnement (.env) ----------------------------------------


class Environnement(BaseSettings):
    """Secrets et paramètres de connexion, lus depuis `.env` (voir `.env.example`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "secheresse"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "secheresse"

    meteofrance_api_key: SecretStr | None = None
    copernicus_user: str | None = None
    copernicus_password: SecretStr | None = None
    dagshub_user: str | None = None
    dagshub_token: SecretStr | None = None

    @property
    def url_postgres(self) -> str:
        mdp = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{mdp}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
