"""Colonnes des indices hebdomadaires (méthodologie D1, D3, D9).

`idx.indice_station` : date de la dernière mesure retenue, avertissement hors référence,
entrée au composite de la semaine. `idx.indice_zone` : détail (stations retenues, campagne
ONDE, période de référence du SPI).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE idx.indice_station
            ADD COLUMN hors_reference boolean NOT NULL DEFAULT false,
            ADD COLUMN date_mesure    date,
            ADD COLUMN dans_composite boolean NOT NULL DEFAULT false;
        ALTER TABLE idx.indice_zone ADD COLUMN detail jsonb;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE idx.indice_station
            DROP COLUMN hors_reference, DROP COLUMN date_mesure, DROP COLUMN dans_composite;
        ALTER TABLE idx.indice_zone DROP COLUMN detail;
        """
    )
