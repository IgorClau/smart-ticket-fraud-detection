"""
Features de comportamento por cartão (camada gold).

Uma linha por cartão: a unidade de fraude é o portador, não a viagem isolada, e
isso garante split por entidade (nenhuma viagem de um cartão vaza entre treino
e teste).

Cada grupo de features nasce de uma hipótese de fraude; nenhuma usa rótulo.

  Volume e rotina ........ venda de créditos, empréstimo (excesso de uso, dias atípicos)
  Diversidade ............ uso por terceiros (linhas/operadoras fora da rotina)
  Horário ................ desvio de finalidade, licença (noite, fim de semana, meio do dia)
  Reembarque ............. replay e clonagem (mesma transação / outra operadora em minutos)
  Validador .............. clonagem (erros de leitura/gravação), uso offline (saldo não debitado)
  Tarifa e veículo ....... conluio (tarifa abaixo da tabela, carro concentrado)
  Recargas e saldo ....... recarga clandestina (valor redondo, fora da dupla passada, empresa rara),
                           endereço falso (recarga sobra frente ao consumo)
  Picos mensais .......... fraude acontece em EPISÓDIOS: o pior mês do cartão comparado
                           ao próprio histórico revela o que a média de 5 anos dilui

As mesmas definições estão em PySpark em src/data_pipeline/spark/03_gold_features.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_EMB_MES = 8          # meses com poucos embarques não entram nos picos de proporção
REEMBARQUE_RAPIDO_MIN = 5
TROCA_OPERADORA_MIN = 15


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.replace(0, np.nan)).fillna(0.0)


def build_card_features(tx: pd.DataFrame, admin: pd.DataFrame | None = None) -> pd.DataFrame:
    """tx: silver.transactions (ordenada por card_id, seq)."""
    tx = tx.sort_values(["card_id", "seq"])
    cards = pd.Index(tx["card_id"].unique(), name="card_id")
    f = pd.DataFrame(index=cards)

    emb = tx[tx["is_embarque"]].copy()
    emb["linha_key"] = emb["operador_display"].astype(str) + "|" + emb["codigo_linha"].astype(str)
    ge = emb.groupby("card_id", sort=False)
    n_emb = ge.size().reindex(cards, fill_value=0)

    # ---- volume e rotina -------------------------------------------------------
    daily = emb.groupby(["card_id", "data"]).size()
    f["n_embarques"] = n_emb
    f["n_dias_ativos"] = daily.groupby(level=0).size()
    f["embarques_por_dia_ativo"] = _ratio(f["n_embarques"], f["n_dias_ativos"])
    f["pico_embarques_dia"] = daily.groupby(level=0).max()
    f["pct_dias_3mais_embarques"] = (daily >= 3).groupby(level=0).mean()
    ts = ge["event_ts"].agg(["min", "max"])
    f["span_dias"] = ((ts["max"] - ts["min"]).dt.days + 1).clip(lower=1)
    f["pct_dias_ativos"] = _ratio(f["n_dias_ativos"], f["span_dias"])

    dias = daily.reset_index()[["card_id", "data"]]
    gap_dias = dias.groupby("card_id")["data"].diff().dt.days
    run_id = (gap_dias != 1).cumsum()
    f["maior_sequencia_dias"] = dias.assign(run=run_id).groupby(["card_id", "run"]).size().groupby(level=0).max()
    f["maior_hiato_dias"] = gap_dias.groupby(dias["card_id"]).max()

    # ---- diversidade -----------------------------------------------------------
    f["n_operadoras"] = ge["operador_display"].nunique()
    f["n_linhas"] = ge["linha_key"].nunique()
    por_linha = emb.groupby(["card_id", "linha_key"]).size()
    f["pct_linha_principal"] = _ratio(por_linha.groupby(level=0).max(), n_emb)
    principal = por_linha.reset_index(name="n").sort_values("n").groupby("card_id").tail(1)
    emb["na_linha_principal"] = emb["linha_key"] == emb["card_id"].map(principal.set_index("card_id")["linha_key"])
    f["pct_intermunicipal"] = (emb["tipo_linha"] == "INTERMUNICIPAL").groupby(emb["card_id"]).mean()
    emb["veic_key"] = emb["operador_display"].astype(str) + "|" + emb["veiculo"].astype(str)
    f["pct_veiculo_mais_usado"] = _ratio(emb.groupby(["card_id", "veic_key"]).size().groupby(level=0).max(), n_emb)

    # ---- horário ---------------------------------------------------------------
    hora = emb["hora"]
    emb["is_noite"] = (hora >= 20) | (hora < 5)
    emb["is_meio_dia"] = hora.between(10, 15)
    f["pct_noite"] = emb["is_noite"].groupby(emb["card_id"]).mean()
    f["pct_meio_dia"] = emb["is_meio_dia"].groupby(emb["card_id"]).mean()
    f["pct_fim_semana"] = (emb["dia_semana"] >= 5).groupby(emb["card_id"]).mean()
    hora_dec = hora + emb["event_ts"].dt.minute / 60
    f["hora_std"] = hora_dec.groupby(emb["card_id"]).std(ddof=0)

    # ---- reembarque ------------------------------------------------------------
    prev = ge.shift()
    gap_min = (emb["event_ts"] - prev["event_ts"]).dt.total_seconds() / 60
    rapido = gap_min < REEMBARQUE_RAPIDO_MIN
    mesmo_dia = emb["data"] == prev["data"]
    f["pct_reembarque_5min"] = _ratio(rapido.groupby(emb["card_id"]).sum(), n_emb)
    f["pct_replay"] = _ratio((rapido & (emb["descricao"] == prev["descricao"])).groupby(emb["card_id"]).sum(), n_emb)
    f["pct_troca_operadora_15min"] = _ratio(
        ((gap_min < TROCA_OPERADORA_MIN) & (emb["operador_display"] != prev["operador_display"]))
        .groupby(emb["card_id"]).sum(), n_emb)
    f["pct_troca_linha_mesmo_dia"] = _ratio(
        (mesmo_dia & (emb["linha_key"] != prev["linha_key"])).groupby(emb["card_id"]).sum(), n_emb)

    # ---- validador ---------------------------------------------------------------
    f["pct_erro_leitura"] = emb["is_erro_leitura"].groupby(emb["card_id"]).mean()
    f["pct_erro_gravacao"] = emb["is_erro_gravacao"].groupby(emb["card_id"]).mean()
    f["pct_saldo_insuficiente"] = emb["is_saldo_insuficiente"].groupby(emb["card_id"]).mean()
    f["pct_inconsistencia_saldo"] = tx["inconsistencia_saldo"].groupby(tx["card_id"]).mean()

    # ---- tarifa e veículo --------------------------------------------------------
    deb = emb[emb["is_debito"]]
    f["pct_tarifa_divergente"] = deb["tarifa_divergente"].groupby(deb["card_id"]).mean()
    f["tarifa_media"] = deb["vd"].groupby(deb["card_id"]).mean()

    # ---- recargas e saldo --------------------------------------------------------
    prox = tx.groupby("card_id", sort=False)[["event_ts", "is_embarque"]].shift(-1)
    rec_mask = tx["is_recarga"]
    rec = tx[rec_mask].copy()
    rec["sem_dupla_passada"] = ~((prox.loc[rec_mask, "event_ts"] == rec["event_ts"])
                                 & prox.loc[rec_mask, "is_embarque"].fillna(False).astype(bool))
    gr = rec.groupby("card_id")
    f["n_recargas"] = gr.size()
    f["recarga_media"] = gr["vd"].mean()
    f["pct_recarga_valor_redondo"] = ((rec["vd"] % 10).abs() < 0.005).groupby(rec["card_id"]).mean()
    f["pct_recarga_sem_dupla_passada"] = rec["sem_dupla_passada"].groupby(rec["card_id"]).mean()
    por_empresa = rec.groupby(["card_id", "empresa_recarga"]).size()
    f["n_empresas_recarga"] = por_empresa.groupby(level=0).size()
    rara = por_empresa[por_empresa <= 3].groupby(level=0).sum()
    f["pct_recarga_empresa_rara"] = _ratio(rara.reindex(cards, fill_value=0), f["n_recargas"].fillna(0))
    total_rec = gr["vd"].sum()
    total_deb = deb["vd"].groupby(deb["card_id"]).sum()
    f["razao_recarga_consumo"] = _ratio(total_rec.reindex(cards, fill_value=0), total_deb.reindex(cards))
    f["saldo_medio"] = tx["saldo"].groupby(tx["card_id"]).mean()

    if admin is not None and not admin.empty:
        ga = admin.groupby("card_id")
        f["n_admin_pendentes"] = ga.size()
        f["valor_admin_pendente"] = ga["valor"].sum()
    else:
        f["n_admin_pendentes"] = 0
        f["valor_admin_pendente"] = 0.0

    # ---- picos mensais (desvio contra o próprio histórico) -------------------------
    emb["fora_linha_principal"] = ~emb["na_linha_principal"]
    mes = emb.groupby(["card_id", "ano_mes"]).agg(
        n=("event_ts", "size"),
        fora=("fora_linha_principal", "sum"),
        noite=("is_noite", "sum"),
        meio_dia=("is_meio_dia", "sum"),
    )
    mediana_n = mes["n"].groupby(level=0).transform("median")
    f["pico_mensal_razao_embarques"] = (mes["n"] / mediana_n).groupby(level=0).max()
    cheios = mes[mes["n"] >= MIN_EMB_MES]
    f["pico_mensal_fora_linha_principal"] = (cheios["fora"] / cheios["n"]).groupby(level=0).max()
    f["pico_mensal_pct_noite"] = (cheios["noite"] / cheios["n"]).groupby(level=0).max()
    f["pico_mensal_pct_meio_dia"] = (mes["meio_dia"] / mes["n"]).where(mes["n"] >= 3).groupby(level=0).max()

    return f.fillna(0.0).reset_index()


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c != "card_id"]
