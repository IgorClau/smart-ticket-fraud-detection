"""
Explicabilidade: por que um cartão foi sinalizado?

SHAP com TreeExplainer sobre o Isolation Forest. O explicador decompõe o
comprimento médio do caminho de isolamento; caminho CURTO = anomalia. Por isso
invertemos o sinal: `contribuicao > 0` significa "esta feature empurrou o cartão
para a anomalia".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.isolation_forest import FraudDetector

DESCRICOES = {
    "embarques_por_dia_ativo": "embarques por dia de uso",
    "pico_embarques_dia": "maior nº de embarques num dia",
    "pct_dias_3mais_embarques": "dias com 3+ embarques",
    "pct_dias_ativos": "dias com uso no período",
    "maior_sequencia_dias": "maior sequência de dias seguidos com uso",
    "maior_hiato_dias": "maior período sem uso",
    "n_operadoras": "operadoras diferentes",
    "n_linhas": "linhas diferentes",
    "pct_linha_principal": "uso concentrado na linha principal",
    "pct_intermunicipal": "embarques em linha intermunicipal",
    "pct_veiculo_mais_usado": "concentração num mesmo carro",
    "pct_noite": "embarques à noite",
    "pct_meio_dia": "embarques no meio do dia",
    "pct_fim_semana": "embarques no fim de semana",
    "hora_std": "variação do horário",
    "pct_reembarque_5min": "reembarques em menos de 5 min",
    "pct_replay": "transação repetida (mesmo carro e linha) em minutos",
    "pct_troca_operadora_15min": "troca de operadora em menos de 15 min",
    "pct_troca_linha_mesmo_dia": "troca de linha no mesmo dia",
    "pct_erro_leitura": "erros de leitura no validador",
    "pct_erro_gravacao": "erros de gravação no validador",
    "pct_saldo_insuficiente": "tentativas com saldo insuficiente",
    "pct_inconsistencia_saldo": "embarque sem débito no saldo",
    "pct_tarifa_divergente": "tarifa diferente da tabela",
    "recarga_media": "valor médio de recarga",
    "pct_recarga_valor_redondo": "recargas de valor redondo",
    "pct_recarga_sem_dupla_passada": "recargas fora da dupla passada",
    "n_empresas_recarga": "empresas diferentes nas recargas",
    "pct_recarga_empresa_rara": "recargas de empresa esporádica",
    "razao_recarga_consumo": "recarga em relação ao consumo",
    "saldo_medio": "saldo médio no cartão",
    "n_admin_pendentes": "recargas pendentes",
    "pico_mensal_razao_embarques": "pico mensal de uso vs. histórico",
    "pico_mensal_fora_linha_principal": "pior mês fora da linha principal",
    "pico_mensal_pct_noite": "pior mês com uso noturno",
    "pico_mensal_pct_meio_dia": "pior mês com uso no meio do dia",
}


def shap_contributions(detector: FraudDetector, df: pd.DataFrame) -> np.ndarray:
    import shap

    explainer = shap.TreeExplainer(detector.model)
    values = explainer.shap_values(detector._matrix(df))
    return -np.asarray(values)


def top_reasons(detector: FraudDetector, df: pd.DataFrame, contrib: np.ndarray, top_k: int) -> list[list[dict]]:
    out = []
    for i in range(len(df)):
        ordem = np.argsort(-contrib[i])[:top_k]
        out.append([{
            "feature": detector.features[j],
            "descricao": DESCRICOES.get(detector.features[j], detector.features[j]),
            "valor": round(float(df.iloc[i][detector.features[j]]), 4),
            "contribuicao": round(float(contrib[i, j]), 4),
        } for j in ordem if contrib[i, j] > 0])
    return out


def reasons_text(reasons: list[dict]) -> str:
    return "; ".join(f"{r['descricao']} (valor {r['valor']:g}, +{r['contribuicao']:.3f})" for r in reasons)
