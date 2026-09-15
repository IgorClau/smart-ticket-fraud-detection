"""
Transformação bronze -> silver.

O que acontece aqui (e não na bronze):
  - deduplicação de lançamentos idênticos;
  - ordem cronológica por cartão, respeitando a dupla passada (REC antes do USADO
    no mesmo instante) e número de sequência do evento;
  - parsing da descrição:
        embarque  "OPERADOR CARRO LINHA SENTIDO"   ex.: "C DAS LIGAS 164 310 V"
        recarga   "Recarga EMPRESA - Pedido N"
    (o pipeline antigo lia o 2º token como "linha"; é o nº do CARRO — corrigido);
  - flags de domínio (débito, recarga, erro, saldo insuficiente);
  - continuidade do saldo: saldo(n) = saldo(n-1) + créditos - débitos. Quebra dessa
    identidade é sinal operacional (validador offline) e vira coluna;
  - enriquecimento com as dimensões de referência (tipo de linha, tarifa de tabela,
    veículo na frota);
  - rótulos do gerador normalizados para o card_id (tabelas separadas: rótulo
    nunca entra na tabela de transações, para não vazar para as features);
  - checagens de qualidade (src.data_pipeline.quality) — erro bloqueia o pipeline.

Uso:
    python -m src.data_pipeline.silver
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.data_pipeline import quality
from src.data_pipeline.reference import build_dimensions

EMBARQUE_RE = r"^(?P<operador_display>.+?)\s+(?P<veiculo>\d+)\s+(?P<codigo_linha>[A-Za-z]*\d+)\s+(?P<sentido>[IV])$"
RECARGA_RE = r"^Recarga\s+(?P<empresa_recarga>.+?)\s+-\s+Pedido\s+(?P<pedido>\d+)$"
DEDUP_KEYS = ["card_id", "event_ts", "tipo", "status_emb", "descricao", "vd", "cart_a", "cart_b"]
BASES_DIR = config.ROOT / "data" / "synthetic" / "bases"


def normalize_card(numero_cartao: pd.Series) -> pd.Series:
    """'42.384452587 - 9' -> '42.384452587-9' (mesmo formato da ingestão)."""
    return numero_cartao.astype(str).str.replace(r"\s+", "", regex=True)


def transform_transactions(tx: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    tx = tx.drop_duplicates(DEDUP_KEYS).copy()

    # ordem cronológica; no empate de timestamp a recarga vem antes (dupla passada)
    tx["_ord_tipo"] = np.where(tx["tipo"] == "REC", 0, 1)
    tx = tx.sort_values(["card_id", "event_ts", "_ord_tipo", "_source_row"],
                        ascending=[True, True, True, False], kind="mergesort")
    tx = tx.drop(columns="_ord_tipo").reset_index(drop=True)
    tx["seq"] = tx.groupby("card_id").cumcount().astype("int32")

    tx["is_embarque"] = tx["tipo"] == "USADO"
    tx["is_recarga"] = tx["tipo"] == "REC"
    tx["is_debito"] = tx["is_embarque"] & (tx["status_emb"] == "NORMAL")
    tx["is_erro_leitura"] = tx["status_emb"] == "ERRO DE LEITURA"
    tx["is_erro_gravacao"] = tx["status_emb"] == "ERRO DE GRAVAÇÃO"
    tx["is_saldo_insuficiente"] = tx["status_emb"] == "SALDO INSUFICIENTE"

    emb = tx["descricao"].where(tx["is_embarque"]).str.extract(EMBARQUE_RE)
    rec = tx["descricao"].where(tx["is_recarga"]).str.extract(RECARGA_RE)
    tx = pd.concat([tx, emb, rec], axis=1)
    tx["veiculo"] = pd.to_numeric(tx["veiculo"], errors="coerce").astype("Int32")

    # continuidade do saldo
    tx["saldo"] = (tx["cart_a"] + tx["cart_b"]).round(2)
    anterior = tx.groupby("card_id")["saldo"].shift()
    esperado = np.select([tx["is_debito"], tx["is_recarga"]], [-tx["vd"], tx["vd"]], 0.0)
    tx["delta_saldo"] = (tx["saldo"] - anterior).round(2)
    tx["inconsistencia_saldo"] = anterior.notna() & ((tx["delta_saldo"] - esperado).abs() > 0.015)

    # enriquecimento com referência
    tx = tx.merge(dims["dim_linha"][["operador_display", "codigo_linha", "tipo_linha", "tarifa_tabela"]],
                  on=["operador_display", "codigo_linha"], how="left")
    frota = dims["dim_veiculo"][["operador_display", "veiculo"]].assign(veiculo_na_frota=True)
    frota["veiculo"] = frota["veiculo"].astype("Int32")
    tx = tx.merge(frota, on=["operador_display", "veiculo"], how="left")
    tx["veiculo_na_frota"] = tx["veiculo_na_frota"].fillna(False).astype(bool)
    tx["tarifa_divergente"] = (tx["is_debito"] & tx["tarifa_tabela"].notna()
                               & ((tx["vd"] - tx["tarifa_tabela"]).abs() > 0.005))

    # atributos de calendário
    tx["data"] = tx["event_ts"].dt.normalize()
    tx["hora"] = tx["event_ts"].dt.hour.astype("int8")
    tx["dia_semana"] = tx["event_ts"].dt.dayofweek.astype("int8")
    tx["ano_mes"] = tx["event_ts"].dt.strftime("%Y-%m")

    # merge não preserva a ordem: restaura (card_id, seq)
    return tx.sort_values(["card_id", "seq"]).reset_index(drop=True)


def transform(bronze_dir: Path, silver_dir: Path, bases_dir: Path = BASES_DIR) -> dict:
    t0 = time.time()
    silver_dir.mkdir(parents=True, exist_ok=True)

    dims = build_dimensions(bases_dir)
    for nome, df in dims.items():
        df.to_parquet(silver_dir / f"{nome}.parquet", index=False)

    files = pd.read_parquet(bronze_dir / "files.parquet")
    tx_bronze = pd.read_parquet(bronze_dir / "transactions")
    tx = transform_transactions(tx_bronze, dims)

    cards = (files.dropna(subset=["card_id"])
             .drop_duplicates("card_id")[["card_id", "nome", "arquivo"]]
             .reset_index(drop=True))

    admin = pd.read_parquet(bronze_dir / "admin_pendentes").drop_duplicates(
        ["card_id", "data_compra", "pedido", "valor"])

    labels = None
    if (bronze_dir / "labels.parquet").exists():
        labels = pd.read_parquet(bronze_dir / "labels.parquet")
        labels = labels.drop_duplicates("card_id")
        labels.to_parquet(silver_dir / "labels_cartao.parquet", index=False)
    if (bronze_dir / "labels_eventos.parquet").exists():
        lev = pd.read_parquet(bronze_dir / "labels_eventos.parquet")
        lev["card_id"] = normalize_card(lev["numero_cartao"])
        lev["event_ts"] = pd.to_datetime(lev["event_ts"])
        lev.drop(columns=["numero_cartao"]).to_parquet(silver_dir / "labels_eventos.parquet", index=False)

    checks = (quality.check_transactions(tx) + quality.check_cards(cards, tx, files)
              + quality.check_labels(labels, cards))
    report = quality.write_report(checks, silver_dir / "quality_report.json")
    quality.enforce(checks)

    tx.to_parquet(silver_dir / "transactions.parquet", index=False)
    cards.to_parquet(silver_dir / "cards.parquet", index=False)
    admin.to_parquet(silver_dir / "recargas_pendentes.parquet", index=False)

    summary = {"linhas_bronze": len(tx_bronze), "linhas_silver": len(tx),
               "duplicatas_removidas": len(tx_bronze) - len(tx), "cartoes": len(cards),
               "checks": f"{report['aprovadas']}/{report['total']} ok, {report['alertas']} alerta(s)",
               "segundos": round(time.time() - t0, 1)}
    print("silver OK:", summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="bronze -> silver")
    ap.add_argument("--bronze-dir", type=Path, default=config.path("bronze_dir"))
    ap.add_argument("--silver-dir", type=Path, default=config.path("silver_dir"))
    args = ap.parse_args()
    transform(args.bronze_dir, args.silver_dir)


if __name__ == "__main__":
    main()
