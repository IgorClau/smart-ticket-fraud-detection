"""
Treino, avaliação, explicabilidade e perfis.

1. Split estratificado POR CARTÃO (entidade) em treino/teste.
2. Isolation Forest treinado sem rótulo no treino; LOF e um classificador
   supervisionado (teto de sinal) como benchmarks — todos avaliados no teste.
3. Recall por tipo de fraude na fila de auditoria.
4. Modelo final re-treinado em todos os cartões (não usa rótulo) e salvo como
   artefato único para a API; score de todos os cartões vai para a gold.
5. SHAP dos cartões em alerta e clusters de perfil.

Saídas:
    mlops/artifacts/model.joblib, model_card.json
    mlops/reports/metrics.json, metrics.md, recall_por_tipo.csv,
                 alertas_explicados.csv, clusters_perfil.csv, figures/*.png
    gold/card_scores.parquet (entrada do Power BI e da API)

Uso:
    python -m src.training.train
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.neighbors import LocalOutlierFactor

from src import config
from src.models import clustering, explain
from src.models.evaluation import ranking_metrics, recall_by_fraud_type
from src.models.isolation_forest import FraudDetector
from src.training import figures


def load_dataset(gold_dir: Path, silver_dir: Path) -> pd.DataFrame:
    feats = pd.read_parquet(gold_dir / "card_features.parquet")
    cards = pd.read_parquet(silver_dir / "cards.parquet")[["card_id", "nome"]]
    df = feats.merge(cards, on="card_id", how="left")
    lab = silver_dir / "labels_cartao.parquet"
    if lab.exists():
        labels = pd.read_parquet(lab)[["card_id", "classe", "is_fraude", "tipos_fraude"]]
        df = df.merge(labels, on="card_id", how="left")
    return df


def _benchmarks(cfg: dict, feats: list[str], det: FraudDetector, tr: pd.DataFrame, te: pd.DataFrame) -> dict:
    lof = LocalOutlierFactor(novelty=True, **cfg["benchmarks"]["local_outlier_factor"])
    lof.fit(det._matrix(tr))
    gb = HistGradientBoostingClassifier(**cfg["benchmarks"]["supervised_gradient_boosting"])
    gb.fit(tr[feats].astype(float), tr["is_fraude"].astype(int))
    return {
        "Isolation Forest (produção)": det.score(te),
        "LOF": -lof.score_samples(det._matrix(te)),
        "Gradient Boosting supervisionado (teto)": gb.predict_proba(te[feats].astype(float))[:, 1],
    }


def train(gold_dir: Path, silver_dir: Path, artifacts_dir: Path, reports_dir: Path) -> dict:
    t0 = time.time()
    cfg = config.model_config()
    feats = cfg["features"]
    ev = cfg["evaluation"]
    audit = ev["audit_fraction"]
    fig_dir = reports_dir / "figures"
    reports_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataset(gold_dir, silver_dir)
    rotulado = "is_fraude" in df.columns and df["is_fraude"].notna().all()
    metrics: dict = {"n_cartoes": len(df), "rotulado": bool(rotulado)}

    # ---- avaliação honesta: treino/teste por cartão --------------------------
    if rotulado:
        df["is_fraude"] = df["is_fraude"].astype(int)
        tr, te = train_test_split(df, test_size=ev["test_size"], random_state=ev["random_state"],
                                  stratify=df["is_fraude"])
        det_eval = FraudDetector(feats, cfg["isolation_forest"]).fit(tr, audit)
        scores = _benchmarks(cfg, feats, det_eval, tr, te)
        y = te["is_fraude"].to_numpy()
        metrics["teste"] = {nome: ranking_metrics(y, s, audit) for nome, s in scores.items()}
        metrics["teste_fila_do_tamanho_da_prevalencia"] = {
            nome: ranking_metrics(y, s, float(y.mean())) for nome, s in scores.items()}

        te_if = te.assign(anomaly_score=scores["Isolation Forest (produção)"])
        por_tipo = recall_by_fraud_type(te_if, "anomaly_score", audit)
        por_tipo.to_csv(reports_dir / "recall_por_tipo.csv", index=False)
        metrics["recall_por_classe"] = {
            c: round(float((te_if.loc[te_if["classe"] == c, "anomaly_score"]
                            >= np.sort(te_if["anomaly_score"])[::-1][int(round(len(te_if) * audit)) - 1]).mean()), 3)
            for c in ("Fraudulento", "Suspeito")}
        figures.pr_curves(y, scores, fig_dir / "pr_curves.png")
        figures.recall_by_type(por_tipo, fig_dir / "recall_por_tipo.png")

    # ---- modelo final (todos os cartões, sem rótulo) --------------------------
    det = FraudDetector(feats, cfg["isolation_forest"]).fit(df, audit)
    pred = det.predict(df)
    scored = pd.concat([df, pred], axis=1).sort_values("anomaly_score", ascending=False)
    scored["rank"] = np.arange(1, len(scored) + 1)

    # ---- explicabilidade dos alertas ------------------------------------------
    alertas = scored[scored["alerta"] == 1]
    contrib = explain.shap_contributions(det, alertas)
    razoes = explain.top_reasons(det, alertas, contrib, cfg["explainability"]["top_k_reasons"])
    alertas_exp = alertas[["rank", "card_id", "nome", "anomaly_score", "percentil"]
                          + [c for c in ("classe", "tipos_fraude") if c in alertas.columns]].copy()
    alertas_exp["principais_motivos"] = [explain.reasons_text(r) for r in razoes]
    alertas_exp["motivo_principal"] = [r[0]["descricao"] if r else "" for r in razoes]
    alertas_exp.to_csv(reports_dir / "alertas_explicados.csv", index=False)
    figures.shap_importance(contrib, feats, fig_dir / "shap_importancia.png")

    # ---- perfis ----------------------------------------------------------------
    cl = cfg["clustering"]
    labels, info = clustering.fit_clusters(scored, feats, cl["k_min"], cl["k_max"], cl["random_state"])
    scored["cluster"] = labels
    prof = clustering.profile(scored, labels)
    prof.to_csv(reports_dir / "clusters_perfil.csv", index=False)
    metrics["clusters"] = info

    if rotulado:
        figures.score_distribution(scored, det.threshold, fig_dir / "score_distribuicao.png")

    # ---- persistência ----------------------------------------------------------
    out_cols = ["card_id", "nome", "anomaly_score", "percentil", "alerta", "rank", "cluster"]
    card_scores = scored[out_cols].merge(alertas_exp[["card_id", "motivo_principal", "principais_motivos"]],
                                         on="card_id", how="left")
    if rotulado:
        card_scores = card_scores.merge(df[["card_id", "classe", "is_fraude", "tipos_fraude"]], on="card_id")
    card_scores.to_parquet(gold_dir / "card_scores.parquet", index=False)

    det.metadata = {
        "model_name": cfg["model_name"], "version": cfg["version"],
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_cartoes_treino": len(df), "audit_fraction": audit, "threshold": det.threshold,
    }
    det.save(artifacts_dir / "model.joblib")
    card = {**det.metadata, "features": feats, "params": cfg["isolation_forest"],
            "metricas_teste": metrics.get("teste", {}).get("Isolation Forest (produção)")}
    (artifacts_dir / "model_card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

    metrics["n_alertas"] = int(pred["alerta"].sum())
    metrics["segundos"] = round(time.time() - t0, 1)
    (reports_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (reports_dir / "metrics.md").write_text(render_markdown(metrics, prof), encoding="utf-8")
    print("train OK:", {k: metrics[k] for k in ("n_cartoes", "n_alertas", "segundos")})
    if rotulado:
        for nome, m in metrics["teste"].items():
            print(f"  {nome:<42} ROC-AUC={m['roc_auc']:.3f} PR-AUC={m['pr_auc']:.3f} "
                  f"precisão@{audit:.0%}={m['precisao_topk']:.3f} recall@{audit:.0%}={m['recall_topk']:.3f}")
    return metrics


def render_markdown(m: dict, prof: pd.DataFrame) -> str:
    linhas = ["# Métricas do modelo", "",
              f"Cartões: **{m['n_cartoes']}** · alertas (fila de auditoria): **{m.get('n_alertas', '-')}**", ""]
    if m.get("teste"):
        linhas += ["## Teste (30% dos cartões, estratificado)", "",
                   "| Modelo | ROC-AUC | PR-AUC | Precisão@fila | Recall@fila | Lift |",
                   "|---|---|---|---|---|---|"]
        for nome, x in m["teste"].items():
            linhas.append(f"| {nome} | {x['roc_auc']:.3f} | {x['pr_auc']:.3f} | {x['precisao_topk']:.3f} "
                          f"| {x['recall_topk']:.3f} | {x['lift_topk']} |")
        x = next(iter(m["teste"].values()))
        linhas += ["", f"Prevalência de fraude no teste: {x['prevalencia']:.1%} · fila de auditoria = "
                       f"{x['fila_auditoria']} cartões.", "",
                   "Fila do tamanho da prevalência (quantos fraudadores cabem se revisarmos tantos cartões "
                   "quanto o nº esperado de fraudes):", "",
                   "| Modelo | Precisão | Recall |", "|---|---|---|"]
        for nome, x in m["teste_fila_do_tamanho_da_prevalencia"].items():
            linhas.append(f"| {nome} | {x['precisao_topk']:.3f} | {x['recall_topk']:.3f} |")
        linhas += ["", f"Recall na fila por classe real: {m['recall_por_classe']}", ""]
    linhas += [f"## Perfis (KMeans, k={m['clusters']['k']})", "", prof.to_markdown(index=False), ""]
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description="treino e avaliação")
    ap.add_argument("--gold-dir", type=Path, default=config.path("gold_dir"))
    ap.add_argument("--silver-dir", type=Path, default=config.path("silver_dir"))
    ap.add_argument("--artifacts-dir", type=Path, default=config.path("artifacts_dir"))
    ap.add_argument("--reports-dir", type=Path, default=config.path("reports_dir"))
    args = ap.parse_args()
    train(args.gold_dir, args.silver_dir, args.artifacts_dir, args.reports_dir)


if __name__ == "__main__":
    main()
