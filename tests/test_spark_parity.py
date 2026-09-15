"""
Paridade pandas x PySpark das features da gold.

Roda no container Spark (pyspark >= 4 + delta):
    docker compose --profile spark run --rm spark pytest -q tests/test_spark_parity.py
Fora dele é pulado.
"""
import numpy as np
import pandas as pd
import pytest

pyspark = pytest.importorskip("pyspark")
if int(pyspark.__version__.split(".")[0]) < 4:
    pytest.skip("requer pyspark >= 4 (container docker/Dockerfile.spark)", allow_module_level=True)
try:
    from pyspark.sql import SparkSession

    SparkSession.builder.master("local[1]").getOrCreate()
except Exception as exc:  # databricks-connect sem sessão remota, Java ausente...
    pytest.skip(f"Spark local indisponível: {exc}", allow_module_level=True)

from src import config  # noqa: E402
from src.data_pipeline.silver import transform_transactions  # noqa: E402
from src.data_pipeline.spark.common import get_spark  # noqa: E402
from src.data_pipeline.spark.features_spark import build_card_features as spark_features  # noqa: E402
from src.feature_engineering.features import build_card_features as pandas_features  # noqa: E402
from tests.conftest import passageiro_para_bronze, seed_com  # noqa: E402
from src.data_generator.viacard.motor import gerar_passageiro  # noqa: E402

FEATURES = config.model_config()["features"]


def test_features_spark_iguais_ao_pandas(bases, dims):
    seeds = [seed_com(bases, lambda p: p.perfil.classe == "Regular"),
             seed_com(bases, lambda p: "Replay" in p.perfil.fraudes),
             seed_com(bases, lambda p: "Uso offline" in p.perfil.fraudes),
             seed_com(bases, lambda p: "Recarga clandestina" in p.perfil.fraudes)]
    bronze = pd.concat([passageiro_para_bronze(gerar_passageiro(s, bases), f"C{s}") for s in seeds])
    silver = transform_transactions(bronze, dims)

    esperado = pandas_features(silver).set_index("card_id").sort_index()

    spark = get_spark()
    sdf = spark.createDataFrame(silver.astype({"veiculo": "float64"}).drop(columns=["_source_row"]))
    obtido = spark_features(sdf).toPandas().set_index("card_id").sort_index()

    for col in FEATURES:
        np.testing.assert_allclose(obtido[col].astype(float), esperado[col].astype(float),
                                   rtol=1e-6, atol=1e-9, err_msg=col)
