"""
Camada gold: features por cartão + tabelas agregadas para o Power BI.

    gold/card_features.parquet          1 linha por cartão (entrada do modelo e da API)
    gold/fato_embarques_diario.parquet  cartão x dia x linha (consumo do dashboard)
    gold/fato_embarques_mensal.parquet  cartão x mês x linha (fato leve: padrão do Power BI)
    gold/fato_recargas_mensal.parquet   cartão x mês x empresa
    gold/dim_linha.parquet              referência de linhas/tarifas

Uso:
    python -m src.feature_engineering.build
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from src import config
from src.feature_engineering.features import build_card_features, feature_columns


def build_bi_tables(tx: pd.DataFrame) -> dict[str, pd.DataFrame]:
    emb = tx.loc[tx["is_embarque"], ["card_id", "data", "operador_display", "codigo_linha", "tipo_linha",
                                     "is_debito", "vd", "is_erro_leitura", "is_erro_gravacao", "hora"]]
    emb = emb.assign(valor_debitado=emb["vd"].where(emb["is_debito"], 0.0),
                     n_erros=emb["is_erro_leitura"] | emb["is_erro_gravacao"],
                     n_noite=(emb["hora"] >= 20) | (emb["hora"] < 5))
    fato_emb = (emb.groupby(["card_id", "data", "operador_display", "codigo_linha", "tipo_linha"],
                            dropna=False, observed=True)
                .agg(n_embarques=("vd", "size"), n_debitos=("is_debito", "sum"),
                     valor_debitado=("valor_debitado", "sum"), n_erros=("n_erros", "sum"),
                     n_noite=("n_noite", "sum"))
                .reset_index())
    rec = tx[tx["is_recarga"]]
    fato_rec = (rec.groupby(["card_id", "ano_mes", "empresa_recarga"], observed=True)
                .agg(n_recargas=("vd", "size"), valor_recarregado=("vd", "sum"))
                .reset_index())
    return {"fato_embarques_diario": fato_emb, "fato_embarques_mensal": fato_embarques_mensal(fato_emb),
            "fato_recargas_mensal": fato_rec}


def fato_embarques_mensal(diario: pd.DataFrame) -> pd.DataFrame:
    """Cartão x mês x linha a partir do fato diário (o que o modelo do Power BI consome)."""
    d = diario.assign(ano_mes=pd.to_datetime(diario["data"]).dt.strftime("%Y-%m"))
    return (d.groupby(["card_id", "ano_mes", "operador_display", "codigo_linha", "tipo_linha"],
                      dropna=False, observed=True)
            .agg(n_embarques=("n_embarques", "sum"), n_debitos=("n_debitos", "sum"),
                 valor_debitado=("valor_debitado", "sum"), n_erros=("n_erros", "sum"),
                 n_noite=("n_noite", "sum"), dias_com_uso=("data", "nunique"))
            .reset_index())


def build(silver_dir: Path, gold_dir: Path, bi_tables: bool = True) -> dict:
    t0 = time.time()
    gold_dir.mkdir(parents=True, exist_ok=True)
    tx = pd.read_parquet(silver_dir / "transactions.parquet")
    admin = pd.read_parquet(silver_dir / "recargas_pendentes.parquet")

    feats = build_card_features(tx, admin)
    feats.to_parquet(gold_dir / "card_features.parquet", index=False)
    summary = {"cartoes": len(feats), "features": len(feature_columns(feats))}

    if bi_tables:
        for nome, df in build_bi_tables(tx).items():
            df.to_parquet(gold_dir / f"{nome}.parquet", index=False)
            summary[nome] = len(df)
        pd.read_parquet(silver_dir / "dim_linha.parquet").to_parquet(gold_dir / "dim_linha.parquet", index=False)

    summary["segundos"] = round(time.time() - t0, 1)
    print("gold OK:", summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="silver -> gold")
    ap.add_argument("--silver-dir", type=Path, default=config.path("silver_dir"))
    ap.add_argument("--gold-dir", type=Path, default=config.path("gold_dir"))
    ap.add_argument("--sem-bi", action="store_true", help="só card_features")
    args = ap.parse_args()
    build(args.silver_dir, args.gold_dir, bi_tables=not args.sem_bi)


if __name__ == "__main__":
    main()
