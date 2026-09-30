.PHONY: help install dvc-auth up down db-roles referentiels ingest reference hebdo db-rebuild config test lint format

PIPELINE = uv run python -m pipeline

help:  ## Liste des commandes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Installe l'environnement Python
	uv sync

dvc-auth:  ## Copie les identifiants DagsHub de .env dans .dvc/config.local (non versionné)
	@test -f .env || { echo ".env manquant (voir .env.example)"; exit 1; }
	@set -a; . ./.env; set +a; \
	test -n "$$DAGSHUB_USER" -a -n "$$DAGSHUB_TOKEN" || { echo "DAGSHUB_USER ou DAGSHUB_TOKEN vide dans .env"; exit 1; }; \
	uv run dvc remote modify --local origin auth basic && \
	uv run dvc remote modify --local origin user "$$DAGSHUB_USER" && \
	uv run dvc remote modify --local origin password "$$DAGSHUB_TOKEN" && \
	echo "Identifiants DagsHub configurés pour le remote DVC « origin »"

up:  ## Démarre PostGIS
	docker compose up -d --wait

down:  ## Arrête PostGIS (le volume est conservé)
	docker compose down

db-roles:  ## (Re)crée le rôle en lecture seule pour QGIS et le dashboard
	docker compose exec -T postgis /docker-entrypoint-initdb.d/20_role_lecteur.sh

config:  ## Valide et affiche la configuration du territoire
	$(PIPELINE) config

referentiels:  ## Communes, mailles SIM et stations -> data/referentiels/
	$(PIPELINE) referentiels

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
