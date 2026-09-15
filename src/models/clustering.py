"""
Perfis de uso (clustering) — Fase 5 do case.

KMeans sobre as features padronizadas, com k escolhido pelo silhouette. Os
clusters descrevem o comportamento NORMAL predominante (ex.: rotina 6x1 numa
linha só, plantonista 12x36, usuário de folga); a detecção de anomalia mede o
desvio. Com rótulos, a taxa de fraude por cluster mostra onde a fraude se esconde.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

PERFIL_COLS = ["embarques_por_dia_ativo", "pct_dias_ativos", "pct_linha_principal", "n_linhas",
               "pct_fim_semana", "pct_noite", "pct_meio_dia", "maior_hiato_dias", "saldo_medio"]


def fit_clusters(df: pd.DataFrame, features: list[str], k_min: int, k_max: int,
                 random_state: int) -> tuple[np.ndarray, dict]:
    X = StandardScaler().fit_transform(df[features].astype(float).fillna(0.0))
    X = np.clip(X, -5, 5)                    # outliers extremos não ditam os centróides
    sample = min(len(X), 3000)
    scores = {}
    for k in range(k_min, k_max + 1):
        labels = KMeans(n_clusters=k, n_init=10, random_state=random_state).fit_predict(X)
        scores[k] = float(silhouette_score(X, labels, sample_size=sample, random_state=random_state))
    best = max(scores, key=scores.get)
    labels = KMeans(n_clusters=best, n_init=10, random_state=random_state).fit_predict(X)
    return labels, {"k": best, "silhouette": {str(k): round(v, 4) for k, v in scores.items()}}


def profile(df: pd.DataFrame, labels: np.ndarray) -> pd.DataFrame:
    d = df.assign(cluster=labels)
    agg = {c: "median" for c in PERFIL_COLS if c in d.columns}
    prof = d.groupby("cluster").agg(**{c: (c, f) for c, f in agg.items()})
    prof.insert(0, "cartoes", d.groupby("cluster").size())
    if "is_fraude" in d.columns:
        prof["taxa_fraude"] = d.groupby("cluster")["is_fraude"].mean()
    return prof.round(3).reset_index()
