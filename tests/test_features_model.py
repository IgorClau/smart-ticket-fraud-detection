import numpy as np
import pandas as pd
import pytest

from src import config
from src.data_pipeline.silver import transform_transactions
from src.feature_engineering.features import build_card_features
from src.models.isolation_forest import FraudDetector
from tests.conftest import passageiro_para_bronze

FEATURES = config.model_config()["features"]


@pytest.fixture(scope="module")
def feats(passageiro_regular, passageiro_replay, dims):
    bronze = pd.concat([passageiro_para_bronze(passageiro_regular, "A"),
                        passageiro_para_bronze(passageiro_replay, "B")])
    return build_card_features(transform_transactions(bronze, dims)).set_index("card_id")


def test_uma_linha_por_cartao_e_todas_as_features(feats):
    assert list(feats.index) == ["A", "B"]
    assert set(FEATURES) <= set(feats.columns)
    assert not feats[FEATURES].isna().any().any()


def test_replay_aparece_na_feature(feats):
    assert feats.loc["A", "pct_replay"] == 0
    assert feats.loc["B", "pct_replay"] > 0


def test_detector_ranqueia_outlier_e_persiste(tmp_path):
    rng = np.random.default_rng(0)
    normal = pd.DataFrame(rng.normal(0, 1, size=(300, len(FEATURES))), columns=FEATURES)
    outlier = pd.DataFrame([np.full(len(FEATURES), 8.0)], columns=FEATURES)
    det = FraudDetector(FEATURES, {"n_estimators": 100, "random_state": 0}).fit(normal, audit_fraction=0.1)

    assert det.score(outlier)[0] > det.score(normal).max()
    assert det.predict(outlier)["alerta"].iloc[0] == 1
    assert 0 <= det.percentile(det.score(normal)).min() <= det.percentile(det.score(outlier))[0] <= 1

    det.save(tmp_path / "m.joblib")
    np.testing.assert_allclose(FraudDetector.load(tmp_path / "m.joblib").score(normal), det.score(normal))


def test_fato_mensal_preserva_os_totais_do_diario(passageiro_regular, passageiro_replay, dims):
    # o Power BI lê o fato mensal: ele não pode perder nem duplicar embarque ou receita
    from src.feature_engineering.build import build_bi_tables

    bronze = pd.concat([passageiro_para_bronze(passageiro_regular, "A"),
                        passageiro_para_bronze(passageiro_replay, "B")])
    bi = build_bi_tables(transform_transactions(bronze, dims))
    dia, mes = bi["fato_embarques_diario"], bi["fato_embarques_mensal"]
    for col in ("n_embarques", "n_debitos", "n_erros", "n_noite"):
        assert mes[col].sum() == dia[col].sum()
    assert mes["valor_debitado"].sum() == pytest.approx(dia["valor_debitado"].sum())
    assert not mes.duplicated(["card_id", "ano_mes", "operador_display", "codigo_linha", "tipo_linha"]).any()


def test_treino_le_a_gold_em_ordem_fixa(tmp_path):
    # o Spark devolve a gold em outra ordem; o split e o Isolation Forest não podem depender disso
    from src.training.train import load_dataset

    ids = [f"42.00000000{i}-1" for i in range(6)]
    gold, silver = tmp_path / "gold", tmp_path / "silver"
    gold.mkdir(), silver.mkdir()
    pd.DataFrame({"card_id": ids[::-1], "x": range(6)}).to_parquet(gold / "card_features.parquet", index=False)
    pd.DataFrame({"card_id": ids[3:] + ids[:3], "nome": list("abcdef")}).to_parquet(silver / "cards.parquet", index=False)
    df = load_dataset(gold, silver)
    assert df["card_id"].tolist() == ids and df.index.tolist() == list(range(6))
