"""Environnement Alembic : la connexion est fournie par `pipeline.db.migrations.appliquer`."""

from __future__ import annotations

from alembic import context

connexion = context.config.attributes["connexion"]
context.configure(connection=connexion, version_table_schema="public")
with context.begin_transaction():
    context.run_migrations()
