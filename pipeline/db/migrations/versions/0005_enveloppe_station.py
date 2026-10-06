"""Enveloppe de la normale par station (`idx.enveloppe_station`) : minimum, médiane et maximum
de l'échantillon de référence, par mois (nappes, m NGF) ou par semaine ISO (débits, Q7 en l/s).
Chargée depuis `data/normales/enveloppe_station.parquet` (`make reference`).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE idx.enveloppe_station (
            station_id     text NOT NULL REFERENCES ref.station,
            indice         text NOT NULL CHECK (indice IN ('ips', 'debit')),
            pas            text NOT NULL CHECK (pas IN ('mois', 'semaine')),
            periode        smallint NOT NULL,   -- mois 1-12 ou semaine ISO 1-52
            minimum        double precision,
            mediane        double precision,
            maximum        double precision,
            n_annees       integer,
            periode_ref    text,
            hors_reference boolean NOT NULL DEFAULT false,
            PRIMARY KEY (station_id, indice, periode)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE idx.enveloppe_station;")
