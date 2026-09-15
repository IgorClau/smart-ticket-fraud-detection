import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src import config
from src.api.main import app, state
from src.models.isolation_forest import FraudDetector
from tests.conftest import passageiro_para_bronze

FEATURES = config.model_config()["features"]


@pytest.fixture(scope="module")
def client(dims):
    rng = np.random.default_rng(1)
    treino = pd.DataFrame(np.abs(rng.normal(0.5, 0.2, size=(200, len(FEATURES)))), columns=FEATURES)
    det = FraudDetector(FEATURES, {"n_estimators": 60, "random_state": 0}).fit(treino, audit_fraction=0.1)
    det.metadata = {"model_name": "teste", "version": "0"}
    with TestClient(app) as c:
        state.update(detector=det, dims=dims, scores=None)
        yield c


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["modelo_carregado"]


def test_score_features(client):
    r = client.post("/score/features", json={"card_id": "x", "features": {"pct_replay": 0.5}})
    assert r.status_code == 200
    body = r.json()
    assert body["card_id"] == "x" and 0 <= body["percentil"] <= 1 and isinstance(body["alerta"], bool)


def test_score_features_rejeita_feature_desconhecida(client):
    assert client.post("/score/features", json={"features": {"nao_existe": 1}}).status_code == 422


def test_score_transactions(client, passageiro_replay):
    tx = passageiro_para_bronze(passageiro_replay).head(400)
    payload = {"card_id": "42.1-1", "transacoes": [{
        "event_ts": r.event_ts.isoformat(), "tipo": r.tipo, "status_emb": r.status_emb,
        "descricao": r.descricao, "cart_a": r.cart_a, "cart_b": r.cart_b,
        "dc": None if pd.isna(r.dc) else r.dc, "vd": r.vd,
    } for r in tx.itertuples()]}
    r = client.post("/score/transactions", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["anomaly_score"] > 0


def test_card_inexistente(client):
    assert client.get("/cards/nao-existe").status_code == 404
