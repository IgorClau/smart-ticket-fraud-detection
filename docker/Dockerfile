# API de score (FastAPI) — imagem publicada no Azure Container Registry e
# executada no Azure Container Apps. Build a partir da raiz do repositório:
#   docker build -f docker/Dockerfile -t smart-ticket-fraud-api .
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-api.txt .
RUN pip install -r requirements-api.txt

# código + configuração + artefato do modelo + referência (linhas/frota) + scores da última execução
COPY src/ src/
COPY mlops/model_config.yml mlops/pipeline.yml mlops/
COPY mlops/artifacts/ mlops/artifacts/
COPY data/synthetic/bases/ data/synthetic/bases/
COPY data/processed/gold/card_scores.parquet data/processed/gold/card_scores.parquet

RUN useradd --create-home --uid 10001 api && chown -R api:api /app
USER api

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
