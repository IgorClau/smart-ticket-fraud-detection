# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Treino, avaliação e score
# MAGIC
# MAGIC A gold tem uma linha por cartão (milhares de linhas): o treino roda no driver com o
# MAGIC **mesmo** `src.training.train` da versão local. O notebook só faz a ponte Delta <-> Parquet
# MAGIC e devolve os scores para a gold (`card_scores`), de onde o Power BI e a API leem.

# COMMAND ----------

import shutil
import sys
import tempfile
from pathlib import Path


def _find_root():
    for cand in (Path.cwd(), *Path.cwd().parents):
        if (cand / "mlops" / "pipeline.yml").exists():
            return cand
    raise RuntimeError("raiz do repositório não encontrada")


ROOT = _find_root()
sys.path.insert(0, str(ROOT))

from src.data_pipeline.spark.common import _dbutils, get_spark, is_databricks, register_layer, table_path, widget, write_delta  # noqa: E402
from src.training.train import train  # noqa: E402

spark = get_spark()
lake_root = widget("lake_root", str(ROOT / "data" / "processed" / "lakehouse"))
catalog = widget("catalog", "")   # Unity Catalog (Azure): vazio = só caminho (local/Docker)

# COMMAND ----------

tmp = Path(tempfile.mkdtemp(prefix="stf_"))
gold_local, silver_local = tmp / "gold", tmp / "silver"
gold_local.mkdir()
silver_local.mkdir()

spark.read.format("delta").load(table_path(lake_root, "gold", "card_features")).toPandas() \
    .to_parquet(gold_local / "card_features.parquet", index=False)
spark.read.format("delta").load(table_path(lake_root, "silver", "cards")).toPandas() \
    .to_parquet(silver_local / "cards.parquet", index=False)
try:
    spark.read.format("delta").load(table_path(lake_root, "silver", "labels_cartao")).toPandas() \
        .to_parquet(silver_local / "labels_cartao.parquet", index=False)
except Exception:
    print("sem rótulos: avaliação supervisionada será pulada")

metrics = train(gold_local, silver_local, tmp / "artifacts", tmp / "reports")

# COMMAND ----------

import pandas as pd  # noqa: E402

scores = pd.read_parquet(gold_local / "card_scores.parquet")
write_delta(spark.createDataFrame(scores), table_path(lake_root, "gold", "card_scores"))
register_layer(spark, catalog, lake_root, "gold", ["card_scores"])

# artefatos e relatórios versionados por execução no lake
destino = table_path(lake_root, "ml", f"run={metrics.get('segundos', 0)}_{Path(tmp).name}")
if is_databricks():
    _dbutils().fs.cp(f"file:{tmp / 'artifacts'}", f"{destino}/artifacts", recurse=True)
    _dbutils().fs.cp(f"file:{tmp / 'reports'}", f"{destino}/reports", recurse=True)
else:
    shutil.copytree(tmp / "artifacts", Path(destino) / "artifacts", dirs_exist_ok=True)
    shutil.copytree(tmp / "reports", Path(destino) / "reports", dirs_exist_ok=True)
print("score OK:", {"cartoes": len(scores), "alertas": int(scores["alerta"].sum()), "artefatos": destino})
