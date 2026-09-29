.PHONY: help install up down db-roles ingest reference hebdo db-rebuild config test lint format

PIPELINE = uv run python -m pipeline

help:  ## Liste des commandes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Installe l'environnement Python
	uv sync

up:  ## Démarre PostGIS
	docker compose up -d --wait

down:  ## Arrête PostGIS (le volume est conservé)
	docker compose down

db-roles:  ## (Re)crée le rôle en lecture seule pour QGIS et le dashboard
	docker compose exec -T postgis /docker-entrypoint-initdb.d/20_role_lecteur.sh

config:  ## Valide et affiche la configuration du territoire
	$(PIPELINE) config

ingest:  ## Ingestion complète de l'historique
	$(PIPELINE) ingest

reference:  ## Calcul des normales
	$(PIPELINE) reference

hebdo:  ## Job hebdomadaire
	$(PIPELINE) hebdo

db-rebuild:  ## Reconstruit PostGIS depuis data/
	$(PIPELINE) db-rebuild

test:  ## Tests (sans réseau)
	uv run pytest

lint:  ## ruff + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy pipeline tests

format:  ## Formate le code
	uv run ruff check --fix .
	uv run ruff format .
