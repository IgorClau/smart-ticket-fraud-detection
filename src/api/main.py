"""
API de score de fraude (FastAPI).

Endpoints:
    GET  /health                 liveness/readiness (usado pelo Container Apps)
    GET  /model                  model card (versão, features, limiar, métricas)
    GET  /cards/{card_id}        score pré-calculado pelo pipeline (gold/card_scores)
    POST /score/features         pontua um vetor de features já calculado
    POST /score/transactions     recebe as validações de um cartão, calcula as features
                                 com o MESMO código da silver/gold e devolve o score

Configuração por variável de ambiente:
    MODEL_PATH   (padrão mlops/artifacts/model.joblib)
    SCORES_PATH  (padrão data/processed/gold/card_scores.parquet; opcional)
    BASES_DIR    (padrão data/synthetic/bases; referência de linhas/frota)

Rodar local:
    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException

from src import config
from src.api.schemas import (CardScore, FeaturesRequest, Health, Motivo, ScoreResponse,
                             TransacoesRequest)
from src.data_pipeline.reference import build_dimensions
from src.data_pipeline.silver import transform_transactions
from src.feature_engineering.features import build_card_features
from src.models import explain
from src.models.isolation_forest import FraudDetector

MODEL_PATH = Path(os.getenv("MODEL_PATH", config.ROOT / "mlops" / "artifacts" / "model.joblib"))
SCORES_PATH = Path(os.getenv("SCORES_PATH", config.ROOT / "data" / "processed" / "gold" / "card_scores.parquet"))
BASES_DIR = Path(os.getenv("BASES_DIR", config.ROOT / "data" / "synthetic" / "bases"))

state: dict = {"detector": None, "scores": None, "dims": None, "top_k": 4}


def load_state() -> None:
    state["top_k"] = config.model_config()["explainability"]["top_k_reasons"]
    if MODEL_PATH.exists():
        state["detector"] = FraudDetector.load(MODEL_PATH)
    if SCORES_PATH.exists():
        state["scores"] = pd.read_parquet(SCORES_PATH).set_index("card_id")
    if BASES_DIR.exists():
        state["dims"] = build_dimensions(BASES_DIR)


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_state()
    yield


app = FastAPI(title="Smart Ticket Fraud Detection", version="1.0.0", lifespan=lifespan,
              description="Score de anomalia para cartões de bilhetagem eletrônica (ViaCard).")


def _detector() -> FraudDetector:
    if state["detector"] is None:
        raise HTTPException(503, "modelo não carregado (rode src.training.train ou ajuste MODEL_PATH)")
    return state["detector"]


def _score_frame(df: pd.DataFrame, card_id: str | None) -> ScoreResponse:
    det = _detector()
    pred = det.predict(df).iloc[0]
    motivos = explain.top_reasons(det, df, explain.shap_contributions(det, df), state["top_k"])[0]
    return ScoreResponse(card_id=card_id, anomaly_score=round(float(pred["anomaly_score"]), 6),
                         percentil=round(float(pred["percentil"]), 4), alerta=bool(pred["alerta"]),
                         limiar=round(det.threshold, 6), motivos=[Motivo(**m) for m in motivos],
                         modelo=f"{det.metadata.get('model_name')}:{det.metadata.get('version')}")


@app.get("/health", response_model=Health)
def health() -> Health:
    det = state["detector"]
    return Health(status="ok" if det is not None else "degradado", modelo_carregado=det is not None,
                  versao_modelo=det.metadata.get("version") if det else None,
                  cartoes_pontuados=0 if state["scores"] is None else len(state["scores"]))


@app.get("/model")
def model_card() -> dict:
    card = MODEL_PATH.with_name("model_card.json")
    if not card.exists():
        raise HTTPException(404, "model_card.json não encontrado")
    return json.loads(card.read_text(encoding="utf-8"))


@app.get("/cards/{card_id}", response_model=CardScore)
def card_score(card_id: str) -> CardScore:
    scores = state["scores"]
    if scores is None or card_id not in scores.index:
        raise HTTPException(404, f"cartão {card_id} não encontrado na última execução do pipeline")
    r = scores.loc[card_id]
    return CardScore(card_id=card_id, nome=r["nome"], anomaly_score=float(r["anomaly_score"]),
                     percentil=float(r["percentil"]), alerta=bool(r["alerta"]), rank=int(r["rank"]),
                     cluster=int(r["cluster"]),
                     motivo_principal=None if pd.isna(r["motivo_principal"]) else r["motivo_principal"])


@app.post("/score/features", response_model=ScoreResponse)
def score_features(req: FeaturesRequest) -> ScoreResponse:
    det = _detector()
    desconhecidas = sorted(set(req.features) - set(det.features))
    if desconhecidas:
        raise HTTPException(422, f"features desconhecidas: {desconhecidas}")
    row = {f: float(req.features.get(f, 0.0)) for f in det.features}
    return _score_frame(pd.DataFrame([row]), req.card_id)


@app.post("/score/transactions", response_model=ScoreResponse)
def score_transactions(req: TransacoesRequest) -> ScoreResponse:
    if state["dims"] is None:
        raise HTTPException(503, "bases de referência não carregadas (BASES_DIR)")
    tx = pd.DataFrame([t.model_dump() for t in req.transacoes])
    tx["event_ts"] = pd.to_datetime(tx["event_ts"]).dt.tz_localize(None).astype("datetime64[s]")
    tx["card_id"] = req.card_id
    # na API não há arquivo de origem: a ordem recebida faz o papel da linha do extrato
    tx["_source_row"] = range(len(tx), 0, -1)
    silver = transform_transactions(tx, state["dims"])
    feats = build_card_features(silver)
    return _score_frame(feats, req.card_id)
