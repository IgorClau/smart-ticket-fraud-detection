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
