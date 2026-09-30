"""Migrations Alembic du schéma PostGIS (SPEC §5.3)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as ConfigAlembic
from sqlalchemy import Connection

DOSSIER = Path(__file__).parent


def appliquer(connexion: Connection, cible: str = "head") -> None:
    configuration = ConfigAlembic()
    configuration.set_main_option("script_location", str(DOSSIER))
    configuration.attributes["connexion"] = connexion
    command.upgrade(configuration, cible)
