"""Connexion à PostGIS (paramètres lus dans `.env`, jamais dans le code ni la configuration)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from pipeline.config import Environnement


def moteur(url: str | None = None) -> Engine:
    """Moteur SQLAlchemy ; `url` par défaut construite depuis `.env` (tests : base jetable)."""
    return create_engine(url or Environnement().url_postgres, future=True)
