# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze — ingestão dos extratos ViaCard
# MAGIC
# MAGIC Lê os `.xlsx` que o ADF copiou para `raw/`, com `binaryFile` + `mapInPandas`,
# MAGIC reaproveitando o **mesmo parser** da versão local (`src.data_pipeline.ingest.parse_workbook`).
# MAGIC Grava três tabelas Delta sem regra de negócio: `transactions`, `admin_pendentes`, `files`,
# MAGIC mais os rótulos do gerador (`labels`, `labels_eventos`) quando existirem.
# MAGIC
# MAGIC Parâmetros (ADF `baseParameters`): `lake_root`, `raw_path`, `batch_id`.

# COMMAND ----------

import sys
from pathlib import Path


def _find_root():
    for cand in (Path.cwd(), *Path.cwd().parents):
        if (cand / "mlops" / "pipeline.yml").exists():
            return cand
    raise RuntimeError("raiz do repositório não encontrada")


sys.path.insert(0, str(_find_root()))

from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql import types as T  # noqa: E402

from src.data_pipeline.spark.common import get_spark, table_path, widget, write_delta  # noqa: E402

spark = get_spark()
lake_root = widget("lake_root", str(_find_root() / "data" / "processed" / "lakehouse"))
raw_path = widget("raw_path", str(_find_root() / "data" / "raw" / "viacard_v44"))
batch_id = widget("batch_id", "local")
print(lake_root, raw_path, batch_id)

# COMMAND ----------

REGISTRO = T.StructType([
    T.StructField("arquivo", T.StringType()),
    T.StructField("card_id", T.StringType()),
    T.StructField("nome", T.StringType()),
    T.StructField("registro", T.StringType()),       # tx | admin | arquivo
    T.StructField("event_ts", T.TimestampType()),
    T.StructField("tipo", T.StringType()),
    T.StructField("status_emb", T.StringType()),
    T.StructField("descricao", T.StringType()),
    T.StructField("cart_a", T.DoubleType()),
    T.StructField("cart_b", T.DoubleType()),
    T.StructField("dc", T.StringType()),
    T.StructField("vd", T.DoubleType()),
    T.StructField("empresa", T.StringType()),
    T.StructField("pedido", T.StringType()),
    T.StructField("situacao", T.StringType()),
    T.StructField("valor", T.DoubleType()),
    T.StructField("_source_row", T.IntegerType()),
    T.StructField("erro", T.StringType()),
])


def parse_batch(batches):
    """Executa nos executores: bytes do .xlsx -> linhas achatadas."""
    import pandas as pd

    from src.data_pipeline.ingest import parse_workbook

    for pdf in batches:
        rows = []
        for path, content in zip(pdf["path"], pdf["content"]):
            arquivo = path.rsplit("/", 1)[-1]
            try:
                r = parse_workbook(bytes(content))
                erro = None if r["card_id"] else "cartão não encontrado no cabeçalho"
            except Exception as exc:  # arquivo corrompido não derruba o lote
                r, erro = {"card_id": None, "nome": None, "tx": [], "admin": []}, f"{type(exc).__name__}: {exc}"
            base = {"arquivo": arquivo, "card_id": r["card_id"], "nome": r["nome"]}
            rows.append({**base, "registro": "arquivo", "erro": erro, "_source_row": len(r["tx"])})
            for ts, tipo, st, desc, a, b, dc, vd, src in r["tx"]:
                rows.append({**base, "registro": "tx", "event_ts": ts, "tipo": tipo, "status_emb": st,
                             "descricao": desc, "cart_a": a, "cart_b": b, "dc": dc, "vd": vd,
                             "_source_row": src})
            for data, emp, ped, sit, valor, src in r["admin"]:
                rows.append({**base, "registro": "admin", "event_ts": data, "empresa": emp,
                             "pedido": ped, "situacao": sit, "valor": valor, "_source_row": src})
        yield pd.DataFrame(rows, columns=[f.name for f in REGISTRO.fields])


# COMMAND ----------

binarios = (spark.read.format("binaryFile")
            .option("pathGlobFilter", "extrato_de_utilizacao_*.xlsx")
            .option("recursiveFileLookup", "true")
            .load(raw_path)
            .select("path", "content"))
n_arquivos = binarios.count()
particoes = max(8, n_arquivos // 64)

registros = (binarios.repartition(particoes)
             .mapInPandas(parse_batch, schema=REGISTRO)
             .withColumn("_ingested_at", F.current_timestamp())
             .withColumn("_batch_id", F.lit(batch_id))
             .withColumn("_source_file", F.col("arquivo"))
             .cache())

tx = registros.filter("registro = 'tx'").select(
    "card_id", "event_ts", "tipo", "status_emb", "descricao", "cart_a", "cart_b", "dc", "vd",
    "_source_file", "_source_row", "_ingested_at", "_batch_id")
admin = registros.filter("registro = 'admin'").select(
    "card_id", F.col("event_ts").alias("data_compra"), "empresa", "pedido", "situacao", "valor",
    "_source_file", "_source_row", "_ingested_at", "_batch_id")
files = registros.filter("registro = 'arquivo'").select(
    "arquivo", "card_id", "nome", F.col("_source_row").alias("n_tx"), "erro", "_ingested_at", "_batch_id")

write_delta(tx, table_path(lake_root, "bronze", "transactions"))
write_delta(admin, table_path(lake_root, "bronze", "admin_pendentes"))
write_delta(files, table_path(lake_root, "bronze", "files"))

# COMMAND ----------

# Rótulos do gerador (só existem no dataset sintético)
files_df = spark.read.format("delta").load(table_path(lake_root, "bronze", "files"))
opts = {"header": "true", "encoding": "UTF-8", "multiLine": "false"}
try:
    rotulos = spark.read.options(**opts).csv(f"{raw_path}/rotulos.csv")
    manifesto = spark.read.options(**opts).csv(f"{raw_path}/manifesto.csv").select(
        "arquivo", "escala", "n_eventos_fraude", "frac_embarques_fraude")
    labels = (rotulos.join(manifesto, "arquivo", "left")
              .join(files_df.select("arquivo", "card_id"), "arquivo", "inner")
              .withColumn("is_fraude", F.col("is_fraude").cast("int"))
              .withColumn("tipos_fraude", F.coalesce("tipos_fraude", F.lit("")))
              .drop("seed"))
    write_delta(labels, table_path(lake_root, "bronze", "labels"))
    eventos = spark.read.options(**opts).csv(f"{raw_path}/rotulos_eventos.csv")
    write_delta(eventos, table_path(lake_root, "bronze", "labels_eventos"))
except Exception as exc:
    print(f"sem rótulos neste lote: {type(exc).__name__}")

# COMMAND ----------

resumo = files_df.agg(F.count("*").alias("arquivos"), F.sum(F.col("erro").isNotNull().cast("int")).alias("com_erro"),
                      F.sum("n_tx").alias("transacoes")).first().asDict()
print("bronze OK:", resumo)
registros.unpersist()
