# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold — features por cartão e agregados para o Power BI
# MAGIC
# MAGIC As features vêm de `features_spark.build_card_features`, porte PySpark de
# MAGIC `src/feature_engineering/features.py`; `tests/test_spark_parity.py` garante que as duas batem.

# COMMAND ----------

import sys
from pathlib import Path


def _find_root():
    for cand in (Path.cwd(), *Path.cwd().parents):
        if (cand / "mlops" / "pipeline.yml").exists():
            return cand
    raise RuntimeError("raiz do repositório não encontrada")


ROOT = _find_root()
sys.path.insert(0, str(ROOT))

from pyspark.sql import functions as F  # noqa: E402

from src.data_pipeline.spark.common import get_spark, optimize, register_layer, table_path, widget, write_delta  # noqa: E402
from src.data_pipeline.spark.features_spark import build_card_features  # noqa: E402

spark = get_spark()
lake_root = widget("lake_root", str(ROOT / "data" / "processed" / "lakehouse"))
catalog = widget("catalog", "")   # Unity Catalog (Azure): vazio = só caminho (local/Docker)

# COMMAND ----------

tx = spark.read.format("delta").load(table_path(lake_root, "silver", "transactions"))
admin = spark.read.format("delta").load(table_path(lake_root, "silver", "recargas_pendentes"))

features = build_card_features(tx, admin)
write_delta(features, table_path(lake_root, "gold", "card_features"))

# COMMAND ----------

# Agregados para o Power BI (Databricks SQL Warehouse)
emb = tx.filter("is_embarque")
fato_emb = (emb.groupBy("card_id", "data", "operador_display", "codigo_linha", "tipo_linha")
            .agg(F.count("*").alias("n_embarques"), F.sum(F.col("is_debito").cast("int")).alias("n_debitos"),
                 F.sum(F.when(F.col("is_debito"), F.col("vd")).otherwise(0.0)).alias("valor_debitado"),
                 F.sum((F.col("is_erro_leitura") | F.col("is_erro_gravacao")).cast("int")).alias("n_erros"),
                 F.sum(((F.col("hora") >= 20) | (F.col("hora") < 5)).cast("int")).alias("n_noite")))
fato_path = table_path(lake_root, "gold", "fato_embarques_diario")
write_delta(fato_emb, fato_path)
optimize(spark, fato_path, ["card_id"])

# fato leve cartão x mês x linha: é o que o modelo do Power BI consome (mesma regra do pandas)
fato_mes = (spark.read.format("delta").load(fato_path)
            .withColumn("ano_mes", F.date_format("data", "yyyy-MM"))
            .groupBy("card_id", "ano_mes", "operador_display", "codigo_linha", "tipo_linha")
            .agg(F.sum("n_embarques").alias("n_embarques"), F.sum("n_debitos").alias("n_debitos"),
                 F.sum("valor_debitado").alias("valor_debitado"), F.sum("n_erros").alias("n_erros"),
                 F.sum("n_noite").alias("n_noite"), F.countDistinct("data").alias("dias_com_uso")))
write_delta(fato_mes, table_path(lake_root, "gold", "fato_embarques_mensal"))

fato_rec = (tx.filter("is_recarga").groupBy("card_id", "ano_mes", "empresa_recarga")
            .agg(F.count("*").alias("n_recargas"), F.sum("vd").alias("valor_recarregado")))
write_delta(fato_rec, table_path(lake_root, "gold", "fato_recargas_mensal"))
write_delta(spark.read.format("delta").load(table_path(lake_root, "silver", "dim_linha")),
            table_path(lake_root, "gold", "dim_linha"))

features = spark.read.format("delta").load(table_path(lake_root, "gold", "card_features"))
print("gold OK:", {"cartoes": features.count(), "features": len(features.columns) - 1})
print("registradas:", register_layer(spark, catalog, lake_root, "gold",
                                    ["card_features", "fato_embarques_diario", "fato_embarques_mensal",
                                     "fato_recargas_mensal", "dim_linha"]))
