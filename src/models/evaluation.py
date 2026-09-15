"""Métricas com ground truth: ranking (ROC/PR-AUC), fila de auditoria e recall por tipo."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, confusion_matrix, precision_recall_fscore_support,
                             roc_auc_score)


def ranking_metrics(y: np.ndarray, score: np.ndarray, audit_fraction: float) -> dict:
    """Métricas independentes de limiar + desempenho na fila de auditoria (top-k)."""
    k = max(1, int(round(len(y) * audit_fraction)))
    top = np.argsort(-score)[:k]
    alerta = np.zeros_like(y)
    alerta[top] = 1
    p, r, f1, _ = precision_recall_fscore_support(y, alerta, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y, alerta, labels=[0, 1]).ravel()
    return {
        "n": int(len(y)), "prevalencia": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y, score)), 4),
        "pr_auc": round(float(average_precision_score(y, score)), 4),
        "fila_auditoria": k,
        "precisao_topk": round(float(p), 4), "recall_topk": round(float(r), 4), "f1_topk": round(float(f1), 4),
        "lift_topk": round(float(p / y.mean()), 2) if y.mean() > 0 else None,
        "confusao": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def recall_by_fraud_type(df: pd.DataFrame, score_col: str, audit_fraction: float) -> pd.DataFrame:
    """Recall na fila de auditoria por tipo de fraude (um cartão pode ter vários tipos)."""
    k = max(1, int(round(len(df) * audit_fraction)))
    corte = np.sort(df[score_col].to_numpy())[::-1][k - 1]
    d = df.assign(alerta=df[score_col] >= corte)
    rows = []
    tipos = d.loc[d["is_fraude"] == 1, "tipos_fraude"].str.split("|").explode()
    for tipo in sorted(t for t in tipos.dropna().unique() if t):
        sub = d[d["tipos_fraude"].str.split("|").apply(lambda ts: tipo in ts)]
        rows.append({"tipo_fraude": tipo, "cartoes": len(sub),
                     "detectados": int(sub["alerta"].sum()),
                     "recall": round(float(sub["alerta"].mean()), 3),
                     "score_mediano": round(float(sub[score_col].median()), 4)})
    return pd.DataFrame(rows).sort_values("recall", ascending=False).reset_index(drop=True)
