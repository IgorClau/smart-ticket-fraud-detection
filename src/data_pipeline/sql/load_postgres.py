"""
Carrega silver/gold no PostgreSQL e responde as perguntas de negócio.

    docker compose up -d postgres
    python -m src.data_pipeline.sql.load_postgres            # carga (COPY)
    python -m src.data_pipeline.sql.load_postgres --run      # executa 02_perguntas_negocio.sql -> 03_respostas.md

Conexão: PG_DSN (padrão postgresql://stf:stf_local@localhost:5432/bilhetagem).
"""
from __future__ import annotations

import argparse
import io
import os
import re
import time
from pathlib import Path

import pandas as pd
import psycopg2

from src import config

SQL_DIR = Path(__file__).parent
DSN = os.getenv("PG_DSN", "postgresql://stf:stf_local@localhost:5432/bilhetagem")

TX_COLS = ["card_id", "seq", "event_ts", "tipo", "status_emb", "descricao", "operador_display", "veiculo",
           "codigo_linha", "sentido", "empresa_recarga", "cart_a", "cart_b", "saldo", "vd", "is_debito",
           "inconsistencia_saldo"]


def _copy(cur, table: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cur.copy_expert(f"COPY bilhetagem.{table} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


def load(conn) -> None:
    silver, gold = config.path("silver_dir"), config.path("gold_dir")
    with conn.cursor() as cur:
        cur.execute((SQL_DIR / "01_schema.sql").read_text(encoding="utf-8"))
        cur.execute("TRUNCATE bilhetagem.score_cartao, bilhetagem.rotulo_cartao, bilhetagem.transacao, "
                    "bilhetagem.linha, bilhetagem.cartao")
        _copy(cur, "cartao", pd.read_parquet(silver / "cards.parquet")[["card_id", "nome", "arquivo"]])
        _copy(cur, "linha", pd.read_parquet(silver / "dim_linha.parquet")[
            ["operador_display", "codigo_linha", "trajeto", "tipo_linha", "tarifa_tabela"]])
        t = time.time()
        tx = pd.read_parquet(silver / "transactions.parquet", columns=TX_COLS)
        for ini in range(0, len(tx), 1_000_000):
            _copy(cur, "transacao", tx.iloc[ini:ini + 1_000_000])
        print(f"transacao: {len(tx):,} linhas em {time.time() - t:.0f}s")
        if (silver / "labels_cartao.parquet").exists():
            _copy(cur, "rotulo_cartao", pd.read_parquet(silver / "labels_cartao.parquet")[
                ["card_id", "classe", "is_fraude", "tipos_fraude"]])
        if (gold / "card_scores.parquet").exists():
            _copy(cur, "score_cartao", pd.read_parquet(gold / "card_scores.parquet")[
                ["card_id", "anomaly_score", "percentil", "alerta", "rank", "cluster", "motivo_principal"]])
        cur.execute("ANALYZE")
    conn.commit()


def run_queries(conn, out: Path) -> None:
    texto = (SQL_DIR / "02_perguntas_negocio.sql").read_text(encoding="utf-8")
    blocos = re.split(r"^-- name: ", texto, flags=re.M)[1:]
    partes = ["# Respostas às perguntas de negócio", "",
              "Gerado por `python -m src.data_pipeline.sql.load_postgres --run` sobre o lote sintético v4.4.", ""]
    with conn.cursor() as cur:
        cur.execute("SET search_path TO bilhetagem")
        for bloco in blocos:
            cabecalho, sql = bloco.split("\n", 1)
            qid, pergunta = [s.strip() for s in cabecalho.split("|", 1)]
            t = time.time()
            df = pd.read_sql_query(sql, conn)
            partes += [f"## {qid} — {pergunta}", "", f"_{len(df)} linha(s), {time.time() - t:.2f}s_", "",
                       df.head(15).to_markdown(index=False), ""]
            print(f"{qid}: {len(df)} linhas ({time.time() - t:.2f}s)")
    out.write_text("\n".join(partes), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="silver/gold -> PostgreSQL")
    ap.add_argument("--run", action="store_true", help="só executa as perguntas (sem recarregar)")
    args = ap.parse_args()
    with psycopg2.connect(DSN) as conn:
        if not args.run:
            load(conn)
        run_queries(conn, SQL_DIR / "03_respostas.md")


if __name__ == "__main__":
    main()
