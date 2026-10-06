"""Projets QGIS en base (`carto.qgis_projects`) : ouverts depuis un poste distant par le tunnel
SSH (Projet › Ouvrir depuis › PostgreSQL), sans copie de fichier.

Structure imposée par QGIS (stockage de projets PostgreSQL) : nom, métadonnées JSON, contenu
du fichier .qgz. Le projet versionné dans `qgis/` fait foi ; `make db-rebuild` et `make qgis`
l'y chargent.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE carto.qgis_projects (
            name     text PRIMARY KEY,
            metadata jsonb,
            content  bytea
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE carto.qgis_projects;")
