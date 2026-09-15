"""Figuras do relatório de modelagem (PNG em mlops/reports/figures)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import precision_recall_curve  # noqa: E402

AZUL, LARANJA, CINZA = "#2563EB", "#EA580C", "#6B7280"


def _salvar(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def score_distribution(scores: pd.DataFrame, threshold: float, path: Path):
    fig, ax = plt.subplots(figsize=(7, 4))
    bins = np.linspace(scores["anomaly_score"].min(), scores["anomaly_score"].max(), 50)
    for classe, cor in (("Regular", AZUL), ("Suspeito", CINZA), ("Fraudulento", LARANJA)):
        s = scores.loc[scores["classe"] == classe, "anomaly_score"]
        if len(s):
            ax.hist(s, bins=bins, alpha=0.55, color=cor, label=f"{classe} (n={len(s)})")
    ax.axvline(threshold, color="black", ls="--", lw=1, label="limiar da fila de auditoria")
    ax.set_xlabel("score de anomalia (maior = mais suspeito)")
    ax.set_ylabel("cartões")
    ax.set_title("Distribuição do score por classe real")
    ax.legend(frameon=False)
    _salvar(fig, path)


def pr_curves(y: np.ndarray, curvas: dict[str, np.ndarray], path: Path):
    fig, ax = plt.subplots(figsize=(6, 4.5))
    for (nome, s), cor in zip(curvas.items(), (AZUL, CINZA, LARANJA)):
        p, r, _ = precision_recall_curve(y, s)
        ax.plot(r, p, color=cor, lw=2, label=nome)
    ax.axhline(y.mean(), color="black", ls=":", lw=1, label=f"aleatório ({y.mean():.0%})")
    ax.set_xlabel("recall")
    ax.set_ylabel("precisão")
    ax.set_title("Precisão x recall no conjunto de teste")
    ax.legend(frameon=False)
    _salvar(fig, path)


def recall_by_type(tab: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    t = tab.sort_values("recall")
    ax.barh(t["tipo_fraude"], t["recall"], color=AZUL)
    for y, (r, n) in enumerate(zip(t["recall"], t["cartoes"])):
        ax.text(r + 0.01, y, f"{r:.0%} (n={n})", va="center", fontsize=8)
    ax.set_xlim(0, 1.15)
    ax.set_xlabel("recall na fila de auditoria")
    ax.set_title("Detecção por tipo de fraude (Isolation Forest, teste)")
    _salvar(fig, path)


def shap_importance(contrib: np.ndarray, features: list[str], path: Path, top: int = 15):
    imp = pd.Series(np.abs(contrib).mean(axis=0), index=features).sort_values().tail(top)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(imp.index, imp.values, color=LARANJA)
    ax.set_xlabel("|contribuição SHAP| média")
    ax.set_title("O que mais pesa no score (cartões em alerta)")
    _salvar(fig, path)
