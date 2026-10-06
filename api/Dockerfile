# API de l'observatoire (service « api » de docker-compose.yml).
# Code et dépendances dans l'image ; config/ monté en lecture seule par docker-compose.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1

# Dépendances d'abord : couche réutilisée tant que pyproject.toml et uv.lock ne changent pas
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY pipeline ./pipeline
COPY api ./api
COPY dashboard ./dashboard
RUN uv sync --frozen --no-dev

USER nobody
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
