# API de l'observatoire (service « api » de docker-compose.yml).
# Code et dépendances dans l'image ; config/ monté en lecture seule par docker-compose.
#
# Deux étapes : `uv` installe les dépendances du service web dans un environnement Python, puis
# seul cet environnement est copié dans une image Python légère (sans uv). Le groupe `pipeline`
# (pandas, scipy, geopandas, pyarrow, dvc…) est exclu : voir pyproject.toml et
# tests/test_api_legere.py. Le projet lui-même n'est pas installé : l'API tourne depuis /app.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS dependances

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1

# Couche réutilisée tant que pyproject.toml et uv.lock ne changent pas
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-group pipeline --no-install-project


FROM python:3.12-slim-bookworm

WORKDIR /app
COPY --from=dependances /app/.venv /app/.venv
COPY pipeline ./pipeline
COPY api ./api
COPY dashboard ./dashboard

USER nobody
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
