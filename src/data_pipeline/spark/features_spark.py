"""
Features por cartão em PySpark — mesmas definições de src/feature_engineering/features.py.

Fica fora do notebook para ser importável pelo teste de paridade
(tests/test_spark_parity.py), que compara as duas implementações.
"""
from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

MIN_EMB_MES = 8


def ratio(num, den):
    return F.coalesce(num / F.when(den != 0, den), F.lit(0.0))


def build_card_features(tx: DataFrame, admin: DataFrame | None = None) -> DataFrame:
    card = "card_id"
    w_seq = Window.partitionBy(card).orderBy("seq")
    emb = (tx.filter("is_embarque")
           .withColumn("linha_key", F.concat_ws("|", "operador_display", "codigo_linha"))
           .withColumn("veic_key", F.concat_ws("|", "operador_display", F.col("veiculo").cast("long").cast("string")))
           .withColumn("is_noite", (F.col("hora") >= 20) | (F.col("hora") < 5))
           .withColumn("is_meio_dia", F.col("hora").between(10, 15)))

    # ---- linha principal (maior contagem) -------------------------------------
    por_linha = emb.groupBy(card, "linha_key").count()
    principal = (por_linha.withColumn("r", F.row_number().over(
        Window.partitionBy(card).orderBy(F.col("count").desc(), F.col("linha_key").desc())))
        .filter("r = 1").select(card, F.col("linha_key").alias("linha_principal"), F.col("count").alias("n_principal")))
    emb = (emb.join(principal.select(card, "linha_principal"), card)
           .withColumn("fora_linha_principal", F.col("linha_key") != F.col("linha_principal")))

    # ---- reembarque (janela sobre os embarques) --------------------------------
    prev = {c: F.lag(c).over(w_seq) for c in ("event_ts", "descricao", "operador_display", "linha_key", "data")}
    gap_min = (F.col("event_ts").cast("long") - prev["event_ts"].cast("long")) / 60
    emb_g = (emb.withColumn("rapido", F.coalesce(gap_min < 5, F.lit(False)))
             .withColumn("replay", F.col("rapido") & F.coalesce(F.col("descricao") == prev["descricao"], F.lit(False)))
             .withColumn("troca_op", F.coalesce((gap_min < 15) & (F.col("operador_display") != prev["operador_display"]),
                                                F.lit(False)))
             .withColumn("troca_linha", F.coalesce((F.to_date("data") == F.to_date(prev["data"]))
                                                   & (F.col("linha_key") != prev["linha_key"]), F.lit(False))))

    base = emb_g.groupBy(card).agg(
        F.count("*").alias("n_embarques"),
        F.min("event_ts").alias("_ts_min"), F.max("event_ts").alias("_ts_max"),
        F.countDistinct("operador_display").alias("n_operadoras"),
        F.countDistinct("linha_key").alias("n_linhas"),
        F.avg(F.coalesce(F.col("tipo_linha") == "INTERMUNICIPAL", F.lit(False)).cast("double")).alias("pct_intermunicipal"),
        F.avg(F.col("is_noite").cast("double")).alias("pct_noite"),
        F.avg(F.col("is_meio_dia").cast("double")).alias("pct_meio_dia"),
        F.avg((F.col("dia_semana") >= 5).cast("double")).alias("pct_fim_semana"),
        F.stddev_pop(F.col("hora") + F.minute("event_ts") / 60).alias("hora_std"),
        F.sum(F.col("rapido").cast("int")).alias("_rapido"),
        F.sum(F.col("replay").cast("int")).alias("_replay"),
        F.sum(F.col("troca_op").cast("int")).alias("_troca_op"),
        F.sum(F.col("troca_linha").cast("int")).alias("_troca_linha"),
        F.avg(F.col("is_erro_leitura").cast("double")).alias("pct_erro_leitura"),
        F.avg(F.col("is_erro_gravacao").cast("double")).alias("pct_erro_gravacao"),
        F.avg(F.col("is_saldo_insuficiente").cast("double")).alias("pct_saldo_insuficiente"),
        F.avg(F.when(F.col("is_debito"), F.col("tarifa_divergente").cast("double"))).alias("pct_tarifa_divergente"),
        F.avg(F.when(F.col("is_debito"), F.col("vd"))).alias("tarifa_media"),
        F.sum(F.when(F.col("is_debito"), F.col("vd"))).alias("_total_debitado"),
    )
    n = F.col("n_embarques")
    base = (base.withColumn("span_dias", F.greatest(
                F.floor((F.col("_ts_max").cast("long") - F.col("_ts_min").cast("long")) / 86400) + 1, F.lit(1)))
            .withColumn("pct_reembarque_5min", ratio(F.col("_rapido"), n))
            .withColumn("pct_replay", ratio(F.col("_replay"), n))
            .withColumn("pct_troca_operadora_15min", ratio(F.col("_troca_op"), n))
            .withColumn("pct_troca_linha_mesmo_dia", ratio(F.col("_troca_linha"), n)))

    # ---- dias ativos, sequências e hiatos (gaps and islands) -----------------------
    daily = emb.withColumn("dia", F.to_date("data")).groupBy(card, "dia").count()
    w_dia = Window.partitionBy(card).orderBy("dia")
    ilhas = (daily.withColumn("grp", F.date_sub("dia", F.row_number().over(w_dia).cast("int")))
             .groupBy(card, "grp").count().groupBy(card).agg(F.max("count").alias("maior_sequencia_dias")))
    dias = (daily.withColumn("gap", F.datediff("dia", F.lag("dia").over(w_dia)))
            .groupBy(card).agg(F.count("*").alias("n_dias_ativos"), F.max("count").alias("pico_embarques_dia"),
                               F.avg((F.col("count") >= 3).cast("double")).alias("pct_dias_3mais_embarques"),
                               F.max("gap").alias("maior_hiato_dias")))

    veic = emb.groupBy(card, "veic_key").count().groupBy(card).agg(F.max("count").alias("_n_top_veic"))

    # ---- todas as transações ---------------------------------------------------------
    todas = tx.groupBy(card).agg(F.avg(F.col("inconsistencia_saldo").cast("double")).alias("pct_inconsistencia_saldo"),
                                 F.avg("saldo").alias("saldo_medio"))

    # ---- recargas -----------------------------------------------------------------------
    rec = (tx.withColumn("_prox_ts", F.lead("event_ts").over(w_seq))
           .withColumn("_prox_emb", F.lead("is_embarque").over(w_seq))
           .filter("is_recarga")
           .withColumn("sem_dupla", ~F.coalesce((F.col("_prox_ts") == F.col("event_ts")) & F.col("_prox_emb"),
                                                F.lit(False))))
    rec_g = rec.groupBy(card).agg(
        F.count("*").alias("n_recargas"), F.avg("vd").alias("recarga_media"),
        F.avg((F.abs(F.col("vd") % 10) < 0.005).cast("double")).alias("pct_recarga_valor_redondo"),
        F.avg(F.col("sem_dupla").cast("double")).alias("pct_recarga_sem_dupla_passada"),
        F.sum("vd").alias("_total_recarregado"))
    emp = (rec.groupBy(card, "empresa_recarga").count().groupBy(card).agg(
        F.count("*").alias("n_empresas_recarga"),
        F.sum(F.when(F.col("count") <= 3, F.col("count")).otherwise(0)).alias("_rec_rara")))

    # ---- picos mensais -------------------------------------------------------------------
    mes = emb.groupBy(card, "ano_mes").agg(F.count("*").alias("n"),
                                           F.sum(F.col("fora_linha_principal").cast("int")).alias("fora"),
                                           F.sum(F.col("is_noite").cast("int")).alias("noite"),
                                           F.sum(F.col("is_meio_dia").cast("int")).alias("meio_dia"))
    mediana = mes.groupBy(card).agg(F.median("n").alias("_mediana_n"))
    picos = (mes.join(mediana, card).groupBy(card).agg(
        F.max(F.col("n") / F.col("_mediana_n")).alias("pico_mensal_razao_embarques"),
        F.max(F.when(F.col("n") >= MIN_EMB_MES, F.col("fora") / F.col("n"))).alias("pico_mensal_fora_linha_principal"),
        F.max(F.when(F.col("n") >= MIN_EMB_MES, F.col("noite") / F.col("n"))).alias("pico_mensal_pct_noite"),
        F.max(F.when(F.col("n") >= 3, F.col("meio_dia") / F.col("n"))).alias("pico_mensal_pct_meio_dia")))

    out = (base.join(dias, card, "left").join(ilhas, card, "left").join(principal, card, "left")
           .join(veic, card, "left").join(todas, card, "left").join(rec_g, card, "left")
           .join(emp, card, "left").join(picos, card, "left")
           .withColumn("embarques_por_dia_ativo", ratio(n, F.col("n_dias_ativos")))
           .withColumn("pct_dias_ativos", ratio(F.col("n_dias_ativos"), F.col("span_dias")))
           .withColumn("pct_linha_principal", ratio(F.col("n_principal"), n))
           .withColumn("pct_veiculo_mais_usado", ratio(F.col("_n_top_veic"), n))
           .withColumn("pct_recarga_empresa_rara", ratio(F.col("_rec_rara"), F.col("n_recargas")))
           .withColumn("razao_recarga_consumo", ratio(F.coalesce("_total_recarregado", F.lit(0.0)),
                                                      F.col("_total_debitado"))))

    if admin is not None:
        adm = admin.groupBy(card).agg(F.count("*").alias("n_admin_pendentes"), F.sum("valor").alias("valor_admin_pendente"))
        out = out.join(adm, card, "left")
    else:
        out = out.withColumn("n_admin_pendentes", F.lit(0)).withColumn("valor_admin_pendente", F.lit(0.0))

    drop = [c for c in out.columns if c.startswith("_")] + ["linha_principal", "n_principal"]
    return out.drop(*drop).fillna(0)
