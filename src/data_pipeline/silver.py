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


def aplicar_chave_lote(df: pd.DataFrame) -> pd.DataFrame:
    """Torna o card_id único entre lotes: `lote:cartao`.

    Cada lote é uma geração independente e o mesmo número de cartão pode reaparecer
    em outra geração, com nome e histórico diferentes (confirmado nos lotes 1-9).
    Sem isso, dois passageiros distintos virariam um só na camada gold.
    O número original fica em `card_id_origem`.
    """
    if "lote" not in df.columns or df.empty:
        return df
    df = df.copy()
    df["card_id_origem"] = df["card_id"]
    df["card_id"] = df["lote"].astype(str) + ":" + df["card_id"].astype(str)
    return df


def normalize_card(numero_cartao: pd.Series) -> pd.Series:
    """'42.384452587 - 9' -> '42.384452587-9' (mesmo formato da ingestão)."""
    return numero_cartao.astype(str).str.replace(r"\s+", "", regex=True)


def _chave_operadora(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def canonizar_operadora(tx: pd.DataFrame, dim_linha: pd.DataFrame) -> pd.DataFrame:
    """Padroniza o nome da operadora pelo da base de referência.

    Gerações antigas gravam a operadora sem espaços ("CDASLIGAS"), o que quebrava o
    join com as dimensões (14% dos embarques ficavam sem tipo de linha, tarifa de
    tabela e checagem de frota) e separava o mesmo operador entre lotes no Power BI.
    """
    mapa = {k: v for k, v in zip(_chave_operadora(dim_linha["operador_display"]),
                                 dim_linha["operador_display"])}
    chave = _chave_operadora(tx["operador_display"])
    tx["operador_display"] = chave.map(mapa).fillna(tx["operador_display"])
    return tx


def _sem_acento(s: pd.Series) -> pd.Series:
    return (s.astype(str).str.normalize("NFKD").str.encode("ascii", "ignore")
            .str.decode("ascii").str.upper().str.strip())


def canonizar_status(tx: pd.DataFrame) -> pd.DataFrame:
    """'ERRO DE GRAVACAO' -> 'ERRO DE GRAVAÇÃO'.

    Gerações antigas gravam o status sem acento; sem canonizar, o mesmo evento vira
    duas categorias e o embarque com erro deixaria de ser reconhecido.
    """
    mapa = {k: v for k, v in zip(_sem_acento(pd.Series(list(quality.STATUS))), quality.STATUS)}
    tx["status_emb"] = _sem_acento(tx["status_emb"]).map(mapa).fillna(tx["status_emb"])
    return tx


# Defeitos que invalidam o extrato inteiro do cartão: não dá para calcular saldo médio,
# razão recarga/consumo ou tarifa a partir de um histórico que viola as regras do sistema.
MOTIVOS_QUARENTENA = {
    "embarque_sem_tarifa": lambda tx: tx["is_debito"] & ~(tx["vd"] > 0),
    "saldo_acima_do_teto": lambda tx: tx["saldo"] > quality.TETO_CARTAO + 0.01,
    "status_fora_do_dominio": lambda tx: ~tx["status_emb"].isin(quality.STATUS),
    "dc_incoerente": lambda tx: ((tx["is_debito"] & (tx["dc"] != "D"))
                                 | (tx["is_recarga"] & (tx["dc"] != "C"))),
}


def separar_quarentena(tx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tira de circulação os cartões com extrato inconsistente, registrando o motivo.

    Preferimos quarentena por CARTÃO (e não por linha) porque remover linhas quebraria a
    continuidade do saldo do que sobra. O pipeline segue com o resto do lote; a proporção
    de cartões em quarentena vira uma checagem de qualidade.
    """
    marcas = {nome: fn(tx) for nome, fn in MOTIVOS_QUARENTENA.items()}
    suspeitas = pd.DataFrame(marcas)
    linhas_ruins = suspeitas.any(axis=1)
    if not linhas_ruins.any():
        return tx, pd.DataFrame(columns=["card_id", "motivos", "linhas_afetadas"])

    detalhe = (suspeitas[linhas_ruins].assign(card_id=tx.loc[linhas_ruins, "card_id"])
               .groupby("card_id").sum())
    quarentena = pd.DataFrame({
        "card_id": detalhe.index,
        "motivos": ["|".join(c for c in detalhe.columns if linha[c] > 0) for _, linha in detalhe.iterrows()],
        "linhas_afetadas": detalhe.sum(axis=1).to_numpy(),
    }).reset_index(drop=True)
    return tx[~tx["card_id"].isin(quarentena["card_id"])].copy(), quarentena


def transform_transactions(tx: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    tx = tx.drop_duplicates(DEDUP_KEYS).copy()

    # ordem cronológica; no empate de timestamp a recarga vem antes (dupla passada)
    tx["_ord_tipo"] = np.where(tx["tipo"] == "REC", 0, 1)
    tx = tx.sort_values(["card_id", "event_ts", "_ord_tipo", "_source_row"],
                        ascending=[True, True, True, False], kind="mergesort")
    tx = tx.drop(columns="_ord_tipo").reset_index(drop=True)
    tx["seq"] = tx.groupby("card_id").cumcount().astype("int32")

    tx = canonizar_status(tx)
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
    tx = canonizar_operadora(tx, dims["dim_linha"])

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

    files = aplicar_chave_lote(pd.read_parquet(bronze_dir / "files.parquet"))
    tx_bronze = aplicar_chave_lote(pd.read_parquet(bronze_dir / "transactions"))
    tx = transform_transactions(tx_bronze, dims)

    col_cards = [c for c in ("card_id", "nome", "arquivo", "lote", "card_id_origem") if c in files.columns]
    cards = (files.dropna(subset=["card_id"])
             .drop_duplicates("card_id")[col_cards]
             .reset_index(drop=True))

    admin = aplicar_chave_lote(pd.read_parquet(bronze_dir / "admin_pendentes")).drop_duplicates(
        ["card_id", "data_compra", "pedido", "valor"])

    labels = None
    if (bronze_dir / "labels.parquet").exists():
        labels = aplicar_chave_lote(pd.read_parquet(bronze_dir / "labels.parquet"))
        labels = labels.drop_duplicates("card_id")
        labels.to_parquet(silver_dir / "labels_cartao.parquet", index=False)
    if (bronze_dir / "labels_eventos.parquet").exists():
        lev = pd.read_parquet(bronze_dir / "labels_eventos.parquet")
        lev["card_id"] = normalize_card(lev["numero_cartao"])
        lev = aplicar_chave_lote(lev)
        lev["event_ts"] = pd.to_datetime(lev["event_ts"])
        lev.drop(columns=["numero_cartao"]).to_parquet(silver_dir / "labels_eventos.parquet", index=False)

    tx, quarentena = separar_quarentena(tx)
    n_cartoes_lidos = len(cards)
    if not quarentena.empty:
        if "lote" in files.columns:
            quarentena["lote"] = files["lote"].iloc[0]
        quarentena.to_parquet(silver_dir / "quarentena_cartoes.parquet", index=False)
        fora = set(quarentena["card_id"])
        cards = cards[~cards["card_id"].isin(fora)].reset_index(drop=True)
        admin = admin[~admin["card_id"].isin(fora)]
        if labels is not None:
            labels = labels[~labels["card_id"].isin(fora)]
            labels.to_parquet(silver_dir / "labels_cartao.parquet", index=False)

    frac_quarentena = len(quarentena) / max(1, n_cartoes_lidos)
    checks = (quality.check_transactions(tx) + quality.check_cards(cards, tx, files)
              + quality.check_labels(labels, cards)
              + [quality.Check("quarentena_dentro_do_limite", "silver.cards", frac_quarentena <= 0.10,
                               f"{frac_quarentena:.2%} ({len(quarentena)} cartão(ões))", "<= 10%")])
    report = quality.write_report(checks, silver_dir / "quality_report.json")
    quality.enforce(checks)

    tx.to_parquet(silver_dir / "transactions.parquet", index=False)
    cards.to_parquet(silver_dir / "cards.parquet", index=False)
    admin.to_parquet(silver_dir / "recargas_pendentes.parquet", index=False)

    summary = {"linhas_bronze": len(tx_bronze), "linhas_silver": len(tx),
               "cartoes": len(cards), "cartoes_quarentena": len(quarentena),
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
