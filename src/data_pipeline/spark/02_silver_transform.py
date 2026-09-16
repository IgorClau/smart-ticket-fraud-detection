# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver — limpeza, parsing, continuidade de saldo e qualidade
# MAGIC
# MAGIC Versão PySpark de `src/data_pipeline/silver.py` (mesmas regras, mesmos nomes de coluna).
# MAGIC Checagens de qualidade com severidade `erro` interrompem o job — dado quebrado não chega à gold.

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

from pyspark.sql import Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from src.data_pipeline import quality  # noqa: E402
from src.data_pipeline.reference import build_dimensions  # noqa: E402
from src.data_pipeline.spark.common import get_spark, optimize, table_path, widget, write_delta  # noqa: E402

spark = get_spark()
lake_root = widget("lake_root", str(ROOT / "data" / "processed" / "lakehouse"))
bases_dir = widget("bases_dir", str(ROOT / "data" / "synthetic" / "bases"))

# COMMAND ----------

EMBARQUE_RE = r"^(.+?)\s+(\d+)\s+([A-Za-z]*\d+)\s+([IV])$"
RECARGA_RE = r"^Recarga\s+(.+?)\s+-\s+Pedido\s+(\d+)$"
DEDUP_KEYS = ["card_id", "event_ts", "tipo", "status_emb", "descricao", "vd", "cart_a", "cart_b"]

# dimensões de referência: poucas centenas de linhas, lidas no driver e enviadas por broadcast
dims = {k: spark.createDataFrame(v) for k, v in build_dimensions(Path(bases_dir)).items()}
for nome, df in dims.items():
    write_delta(df, table_path(lake_root, "silver", nome))

bronze = spark.read.format("delta").load(table_path(lake_root, "bronze", "transactions"))
n_bronze = bronze.count()

# COMMAND ----------


def extrair(col, pattern, idx):
    return F.nullif(F.regexp_extract(col, pattern, idx), F.lit(""))


w_seq = Window.partitionBy("card_id").orderBy("event_ts", "_ord_tipo", F.col("_source_row").desc())
w_card = Window.partitionBy("card_id").orderBy("seq")

tx = (bronze.dropDuplicates(DEDUP_KEYS)
      .withColumn("_ord_tipo", F.when(F.col("tipo") == "REC", 0).otherwise(1))
      .withColumn("seq", F.row_number().over(w_seq) - 1)
      .drop("_ord_tipo")
      .withColumn("is_embarque", F.col("tipo") == "USADO")
      .withColumn("is_recarga", F.col("tipo") == "REC")
      .withColumn("is_debito", F.col("is_embarque") & (F.col("status_emb") == "NORMAL"))
      .withColumn("is_erro_leitura", F.col("status_emb") == "ERRO DE LEITURA")
      .withColumn("is_erro_gravacao", F.col("status_emb") == "ERRO DE GRAVAÇÃO")
      .withColumn("is_saldo_insuficiente", F.col("status_emb") == "SALDO INSUFICIENTE"))

desc_emb = F.when(F.col("is_embarque"), F.col("descricao"))
desc_rec = F.when(F.col("is_recarga"), F.col("descricao"))
tx = (tx.withColumn("operador_display", extrair(desc_emb, EMBARQUE_RE, 1))
      .withColumn("veiculo", extrair(desc_emb, EMBARQUE_RE, 2).cast("int"))
      .withColumn("codigo_linha", extrair(desc_emb, EMBARQUE_RE, 3))
      .withColumn("sentido", extrair(desc_emb, EMBARQUE_RE, 4))
      .withColumn("empresa_recarga", extrair(desc_rec, RECARGA_RE, 1))
      .withColumn("pedido", extrair(desc_rec, RECARGA_RE, 2)))

# canoniza o status (gerações antigas gravam "ERRO DE GRAVACAO", sem acento)
mapa_status = {"".join(ch for ch in __import__("unicodedata").normalize("NFKD", v)
                       if not __import__("unicodedata").combining(ch)).upper(): v for v in quality.STATUS}
canon_status = F.create_map([F.lit(x) for kv in mapa_status.items() for x in kv])
tx = tx.withColumn("status_emb", F.coalesce(canon_status[F.upper(F.col("status_emb"))], F.col("status_emb")))

# continuidade do saldo: saldo(n) = saldo(n-1) + crédito - débito
anterior = F.lag("saldo").over(w_card)
esperado = (F.when(F.col("is_debito"), -F.col("vd")).when(F.col("is_recarga"), F.col("vd")).otherwise(F.lit(0.0)))
tx = (tx.withColumn("saldo", F.round(F.col("cart_a") + F.col("cart_b"), 2))
      .withColumn("delta_saldo", F.round(F.col("saldo") - anterior, 2))
      .withColumn("inconsistencia_saldo",
                  anterior.isNotNull() & (F.abs(F.col("delta_saldo") - esperado) > 0.015)))

# padroniza o nome da operadora pelo da referência (gerações antigas gravam "CDASLIGAS")
mapa_op = {r["k"]: r["operador_display"] for r in dims["dim_linha"]
           .withColumn("k", F.upper(F.regexp_replace("operador_display", "[^A-Za-z0-9]", "")))
           .select("k", "operador_display").distinct().collect()}
canon = F.create_map([F.lit(x) for kv in mapa_op.items() for x in kv])
tx = tx.withColumn("operador_display", F.coalesce(
    canon[F.upper(F.regexp_replace("operador_display", "[^A-Za-z0-9]", ""))], F.col("operador_display")))

linha = dims["dim_linha"].select("operador_display", "codigo_linha", "tipo_linha", "tarifa_tabela")
frota = dims["dim_veiculo"].select("operador_display", F.col("veiculo").cast("int"),
                                   F.lit(True).alias("veiculo_na_frota"))
tx = (tx.join(F.broadcast(linha), ["operador_display", "codigo_linha"], "left")
      .join(F.broadcast(frota), ["operador_display", "veiculo"], "left")
      .withColumn("veiculo_na_frota", F.coalesce("veiculo_na_frota", F.lit(False)))
      .withColumn("tarifa_divergente", F.col("is_debito") & F.col("tarifa_tabela").isNotNull()
                  & (F.abs(F.col("vd") - F.col("tarifa_tabela")) > 0.005))
      .withColumn("data", F.to_date("event_ts"))
      .withColumn("hora", F.hour("event_ts"))
      .withColumn("dia_semana", (F.dayofweek("event_ts") + 5) % 7)       # 0 = segunda (igual ao pandas)
      .withColumn("ano_mes", F.date_format("event_ts", "yyyy-MM")))

# quarentena: cartões cujo extrato viola as regras do sistema (mesmos motivos do pandas)
ruim = ((F.col("is_debito") & ~(F.col("vd") > 0))
        | (F.col("saldo") > quality.TETO_CARTAO + 0.01)
        | ~F.col("status_emb").isin(*quality.STATUS)
        | (F.col("is_debito") & (F.col("dc") != "D"))
        | (F.col("is_recarga") & (F.col("dc") != "C")))
quarentena = tx.filter(ruim).groupBy("card_id").agg(F.count("*").alias("linhas_afetadas"))
n_quarentena = quarentena.count()
if n_quarentena:
    write_delta(quarentena, table_path(lake_root, "silver", "quarentena_cartoes"))
    tx = tx.join(F.broadcast(quarentena.select("card_id")), "card_id", "left_anti")
print(f"quarentena: {n_quarentena} cartão(ões)")

silver_path = table_path(lake_root, "silver", "transactions")
write_delta(tx, silver_path, partition_by=["ano_mes"])
tx = spark.read.format("delta").load(silver_path)

# COMMAND ----------

# MAGIC %md ### Qualidade (mesmo contrato de `src/data_pipeline/quality.py`)

# COMMAND ----------


def conta(cond):
    return F.sum(F.when(cond, 1).otherwise(0))


prev_ts = F.lag("event_ts").over(Window.partitionBy("card_id").orderBy("seq"))
agg = (tx.withColumn("_fora_ordem", prev_ts.isNotNull() & (F.col("event_ts") < prev_ts))
       .agg(
    conta(F.col("card_id").isNull()).alias("card_id_nao_nulo"),
    conta(F.col("event_ts").isNull()).alias("event_ts_nao_nulo"),
    conta(~F.col("tipo").isin(*quality.TIPOS)).alias("tipo_no_dominio"),
    conta(~F.col("status_emb").isin(*quality.STATUS)).alias("status_no_dominio"),
    conta(~(F.col("vd") > 0)).alias("vd_positivo"),
    conta((F.col("cart_a") < -0.005) | (F.col("cart_b") < -0.005)).alias("carteiras_nao_negativas"),
    conta(F.col("saldo") > quality.TETO_CARTAO + 0.01).alias("saldo_ate_teto"),
    conta((F.col("is_debito") & (F.col("dc") != "D")) | (F.col("is_recarga") & (F.col("dc") != "C"))
          | (F.col("is_embarque") & ~F.col("is_debito") & F.col("dc").isNotNull())).alias("dc_coerente"),
    conta(F.col("is_embarque") & F.col("codigo_linha").isNull()).alias("descricao_embarque_parseada"),
    conta(F.col("is_recarga") & F.col("empresa_recarga").isNull()).alias("descricao_recarga_parseada"),
    conta(F.col("_fora_ordem")).alias("cronologia_por_cartao"),
    conta(~F.year("event_ts").between(2015, 2026)).alias("ano_plausivel"),
    F.avg((F.col("is_embarque") & F.col("tipo_linha").isNull()).cast("double")).alias("linha_existe_na_referencia"),
    F.avg((F.col("is_embarque") & ~F.col("veiculo_na_frota")).cast("double")).alias("veiculo_existe_na_frota"),
)).first().asDict()
duplicatas = tx.count() - tx.dropDuplicates(DEDUP_KEYS).count()

checks = [quality.Check(nome, "silver.transactions", v == 0, str(v), "0")
          for nome, v in agg.items() if not nome.endswith(("referencia", "frota"))]
checks.append(quality.Check("sem_duplicatas", "silver.transactions", duplicatas == 0, str(duplicatas), "0"))
for nome in ("linha_existe_na_referencia", "veiculo_existe_na_frota"):
    checks.append(quality.Check(nome, "silver.transactions", agg[nome] <= 0.001, f"{agg[nome]:.4%}",
                                "<= 0.1%", "alerta"))
for c in checks:
    print(("OK   " if c.ok else "FALHA"), c.severidade, c.nome, c.observado)
quality.enforce(checks)

# COMMAND ----------

cards = (spark.read.format("delta").load(table_path(lake_root, "bronze", "files"))
         .filter("card_id IS NOT NULL").dropDuplicates(["card_id"]).select("card_id", "nome", "arquivo"))
write_delta(cards, table_path(lake_root, "silver", "cards"))
admin = (spark.read.format("delta").load(table_path(lake_root, "bronze", "admin_pendentes"))
         .dropDuplicates(["card_id", "data_compra", "pedido", "valor"]))
write_delta(admin, table_path(lake_root, "silver", "recargas_pendentes"))

try:
    labels = spark.read.format("delta").load(table_path(lake_root, "bronze", "labels")).dropDuplicates(["card_id"])
    write_delta(labels, table_path(lake_root, "silver", "labels_cartao"))
    lev = (spark.read.format("delta").load(table_path(lake_root, "bronze", "labels_eventos"))
           .withColumn("card_id", F.regexp_replace("numero_cartao", r"\s+", ""))
           .withColumn("event_ts", F.to_timestamp("event_ts")).drop("numero_cartao"))
    write_delta(lev, table_path(lake_root, "silver", "labels_eventos"))
except Exception as exc:
    print(f"sem rótulos: {type(exc).__name__}")

optimize(spark, silver_path, ["card_id"])
print("silver OK:", {"linhas_bronze": n_bronze, "linhas_silver": tx.count(), "cartoes": cards.count(),
                     "checks": f"{sum(c.ok for c in checks)}/{len(checks)}"})
