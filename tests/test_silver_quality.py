import pandas as pd
import pytest

from src.data_pipeline import quality
from src.data_pipeline.silver import normalize_card, transform_transactions
from tests.conftest import passageiro_para_bronze


@pytest.fixture(scope="module")
def silver(passageiro_replay, dims):
    return transform_transactions(passageiro_para_bronze(passageiro_replay), dims)


def test_ordem_cronologica_e_sequencia(silver):
    assert silver["event_ts"].is_monotonic_increasing
    assert (silver["seq"].diff().dropna() == 1).all()


def test_dupla_passada_recarga_antes_do_embarque(silver):
    mesmo_instante = silver[silver.duplicated("event_ts", keep=False)]
    for _, grupo in mesmo_instante.groupby("event_ts"):
        if grupo["is_recarga"].any() and grupo["is_embarque"].any():
            assert grupo.iloc[0]["is_recarga"]


def test_descricoes_parseadas_e_referencia(silver):
    emb = silver[silver["is_embarque"]]
    assert emb["codigo_linha"].notna().all() and emb["veiculo"].notna().all()
    assert emb["tipo_linha"].notna().all() and emb["veiculo_na_frota"].all()
    assert silver.loc[silver["is_recarga"], "empresa_recarga"].notna().all()


def test_checks_de_qualidade_passam(silver):
    checks = quality.check_transactions(silver)
    quality.enforce(checks)
    assert all(c.ok for c in checks)


def test_saldo_sem_debito_vira_inconsistencia(dims):
    base = pd.DataFrame([
        {"event_ts": "2024-03-04 07:01:10", "status_emb": "NORMAL", "cart_a": 100.0, "_source_row": 3},
        {"event_ts": "2024-03-04 17:20:31", "status_emb": "NORMAL", "cart_a": 94.1, "_source_row": 2},
        {"event_ts": "2024-03-05 07:03:44", "status_emb": "NORMAL", "cart_a": 94.1, "_source_row": 1},  # offline
    ]).assign(card_id="1", tipo="USADO", descricao="VANGUARDA 12 003 I", cart_b=0.0, dc="D", vd=5.9)
    base["event_ts"] = pd.to_datetime(base["event_ts"])
    tx = transform_transactions(base, dims)
    assert tx["inconsistencia_saldo"].tolist() == [False, False, True]


def test_quality_bloqueia_dado_quebrado(silver):
    quebrado = silver.copy()
    quebrado.loc[quebrado.index[0], "tipo"] = "ESTORNO"
    with pytest.raises(quality.DataQualityError):
        quality.enforce(quality.check_transactions(quebrado))


def test_normalize_card():
    assert normalize_card(pd.Series(["42.384452587 - 9"])).iloc[0] == "42.384452587-9"
