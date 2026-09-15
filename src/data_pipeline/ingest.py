"""
Ingestão raw -> bronze.

Lê os extratos ViaCard (.xlsx) e grava as tabelas bronze em Parquet:

    transactions/          uma linha por lançamento do bloco "EXTRATO DE USO"
    admin_pendentes/       uma linha por recarga do bloco "LANÇAMENTOS ADMINISTRATIVOS"
    files.parquet          uma linha por arquivo (cartão, contagens, erro de leitura)
    labels.parquet         rótulo por extrato do gerador (rotulos.csv + manifesto.csv)
    labels_eventos.parquet rótulo por evento fraudulento (rotulos_eventos.csv, gerador v4.4)

A bronze preserva o conteúdo do arquivo: nenhuma regra de negócio, só nomes de
coluna estáveis e metadados de origem (_source_file, _source_row, _ingested_at).
Parsing da descrição, tipagem de domínio e deduplicação ficam na silver.

Layout de um extrato (coluna A vazia):

    B4 nome                          E4 "Número do Cartão: 42.NNNNNNNNN - D"
    LANÇAMENTOS ADMINISTRATIVOS
    data | empresa | ... | pedido | ... | valor
    EXTRATO DE USO
    Data | Tipo | Tipo Emb. | Descrição | CART A | CART B | D/C | VD | SALDO
    ... cronologia reversa (mais recente no topo)

Leitura com python-calamine (Rust): ~40 ms por extrato, contra ~3 s do openpyxl.

Uso:
    python -m src.data_pipeline.ingest [--raw-dir data/raw/viacard_v44] [--limit 100]
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from python_calamine import CalamineWorkbook

from src import config

CARD_RE = re.compile(r"N[úu]mero do Cart[ãa]o:\s*([\d.]+)\s*-\s*(\d)")
DIGITS_RE = re.compile(r"(\d{3,})")

TX_SCHEMA = pa.schema([
    ("card_id", pa.string()),
    ("event_ts", pa.timestamp("s")),
    ("tipo", pa.string()),
    ("status_emb", pa.string()),
    ("descricao", pa.string()),
    ("cart_a", pa.float64()),
    ("cart_b", pa.float64()),
    ("dc", pa.string()),
    ("vd", pa.float64()),
    ("_source_file", pa.string()),
    ("_source_row", pa.int32()),
    ("_ingested_at", pa.timestamp("s")),
])

ADMIN_SCHEMA = pa.schema([
    ("card_id", pa.string()),
    ("data_compra", pa.timestamp("s")),
    ("empresa", pa.string()),
    ("pedido", pa.string()),
    ("situacao", pa.string()),
    ("valor", pa.float64()),
    ("_source_file", pa.string()),
    ("_source_row", pa.int32()),
    ("_ingested_at", pa.timestamp("s")),
])


def _none(v):
    return None if v is None or v == "" else v


def _num(v) -> float | None:
    v = _none(v)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _str(v) -> str | None:
    v = _none(v)
    return None if v is None else str(v).strip()


def _as_datetime(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return None


def parse_workbook(source: str | Path | bytes) -> dict:
    """Lê um extrato (caminho ou bytes) e devolve {card_id, nome, tx: [...], admin: [...]}.

    Bytes permitem reusar o parser no Spark (`binaryFile` + mapInPandas).
    Aceita os dois layouts de Lançamentos Administrativos que os geradores já
    produziram (v3: "Recarga pendente – Pedido N" na coluna E e situação na H;
    v4.x: número do pedido na coluna F).
    """
    if isinstance(source, (bytes, bytearray)):
        wb = CalamineWorkbook.from_filelike(io.BytesIO(source))
    else:
        wb = CalamineWorkbook.from_path(str(source))
    rows = wb.get_sheet_by_index(0).to_python(skip_empty_area=False)
    card_id = nome = None
    section = None
    tx: list[tuple] = []
    admin: list[tuple] = []
    for row_idx, row in enumerate(rows, start=1):
        row = list(row[:10]) + [""] * (10 - len(row))
        b = row[1]
        if isinstance(b, str):
            label = b.strip().upper()
            if label.startswith(("LANÇAMENTOS ADMINISTRATIVOS", "LANCAMENTOS ADMINISTRATIVOS")):
                section = "admin"
            elif label == "EXTRATO DE USO":
                section = "uso"
            elif card_id is None and isinstance(row[4], str):
                m = CARD_RE.search(row[4])
                if m:
                    card_id = f"{m.group(1)}-{m.group(2)}"
                    nome = b.strip()
            continue  # cabeçalhos, linhas vazias e avisos ("Não há recargas pendentes...")
        ts = _as_datetime(b)
        if ts is None:
            continue
        if section == "admin":
            pedido_src = _none(row[5]) if _none(row[5]) is not None else row[4]
            m = DIGITS_RE.search(str(pedido_src or ""))
            admin.append((ts, _str(row[2]), m.group(1) if m else None,
                          _str(row[7]), _num(row[8]), row_idx))
        elif section == "uso":
            tx.append((ts, _str(row[2]), _str(row[3]), _str(row[4]),
                       _num(row[5]), _num(row[6]), _str(row[7]), _num(row[8]), row_idx))
    return {"card_id": card_id, "nome": nome, "tx": tx, "admin": admin}


def _parse_safe(path: str) -> dict:
    try:
        out = parse_workbook(path)
        out["erro"] = None if out["card_id"] else "cartão não encontrado no cabeçalho"
    except Exception as exc:  # arquivo corrompido não derruba o lote
        out = {"card_id": None, "nome": None, "tx": [], "admin": [], "erro": f"{type(exc).__name__}: {exc}"}
    out["arquivo"] = Path(path).name
    return out


def _to_tables(results: list[dict], ingested_at: datetime) -> tuple[pa.Table, pa.Table]:
    tx_cols = {n: [] for n in TX_SCHEMA.names}
    adm_cols = {n: [] for n in ADMIN_SCHEMA.names}
    for r in results:
        for ts, tipo, st, desc, a, b, dc, vd, src_row in r["tx"]:
            for k, v in zip(TX_SCHEMA.names, (r["card_id"], ts, tipo, st, desc, a, b, dc, vd,
                                              r["arquivo"], src_row, ingested_at)):
                tx_cols[k].append(v)
        for data, emp, ped, sit, valor, src_row in r["admin"]:
            for k, v in zip(ADMIN_SCHEMA.names, (r["card_id"], data, emp, ped, sit, valor,
                                                 r["arquivo"], src_row, ingested_at)):
                adm_cols[k].append(v)
    return (pa.table(tx_cols, schema=TX_SCHEMA), pa.table(adm_cols, schema=ADMIN_SCHEMA))


def load_labels(raw_dir: Path, files: pd.DataFrame) -> pd.DataFrame | None:
    """Rótulos por extrato do gerador, ligados ao cartão pelo nome do arquivo."""
    rot, man = raw_dir / "rotulos.csv", raw_dir / "manifesto.csv"
    if not rot.exists():
        return None
    labels = pd.read_csv(rot, dtype={"arquivo": str, "tipos_fraude": str}, encoding="utf-8")
    if man.exists():
        extra = pd.read_csv(man, encoding="utf-8")
        cols = [c for c in ("arquivo", "escala", "realismo_geral", "validacoes_ok",
                            "n_eventos_fraude", "frac_embarques_fraude") if c in extra.columns]
        labels = labels.merge(extra[cols], on="arquivo", how="left")
    labels = labels.merge(files[["arquivo", "card_id"]], on="arquivo", how="inner")
    labels["tipos_fraude"] = labels["tipos_fraude"].fillna("")
    return labels.drop(columns=["seed"], errors="ignore")


def ingest(raw_dir: Path, bronze_dir: Path, workers: int, part_size: int,
           file_glob: str, limit: int | None = None) -> dict:
    files = sorted(str(p) for p in raw_dir.glob(file_glob))
    if limit:
        files = files[:limit]
    if not files:
        sys.exit(f"Nenhum arquivo {file_glob} em {raw_dir}")

    for sub in ("transactions", "admin_pendentes"):
        shutil.rmtree(bronze_dir / sub, ignore_errors=True)
        (bronze_dir / sub).mkdir(parents=True, exist_ok=True)
    for f in ("labels.parquet", "labels_eventos.parquet"):
        (bronze_dir / f).unlink(missing_ok=True)

    ingested_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    t0 = time.time()
    buffer: list[dict] = []
    file_rows: list[dict] = []
    part = n_tx = n_adm = 0

    def flush():
        nonlocal part, n_tx, n_adm, buffer
        if not buffer:
            return
        tx_t, adm_t = _to_tables(buffer, ingested_at)
        pq.write_table(tx_t, bronze_dir / "transactions" / f"part-{part:05d}.parquet")
        pq.write_table(adm_t, bronze_dir / "admin_pendentes" / f"part-{part:05d}.parquet")
        n_tx += tx_t.num_rows
        n_adm += adm_t.num_rows
        part += 1
        buffer = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, r in enumerate(pool.map(_parse_safe, files, chunksize=16), start=1):
            file_rows.append({"arquivo": r["arquivo"], "card_id": r["card_id"], "nome": r["nome"],
                              "n_tx": len(r["tx"]), "n_admin": len(r["admin"]), "erro": r["erro"]})
            if r["card_id"]:
                buffer.append(r)
            if len(buffer) >= part_size:
                flush()
            if i % 500 == 0 or i == len(files):
                print(f"  [{i:>5}/{len(files)}] {time.time() - t0:6.1f}s", flush=True)
    flush()

    files_df = pd.DataFrame(file_rows)
    files_df["_ingested_at"] = ingested_at
    files_df.to_parquet(bronze_dir / "files.parquet", index=False)

    labels = load_labels(raw_dir, files_df)
    if labels is not None:
        labels.to_parquet(bronze_dir / "labels.parquet", index=False)
    rot_ev = raw_dir / "rotulos_eventos.csv"
    n_ev = 0
    if rot_ev.exists():
        lev = pd.read_csv(rot_ev, encoding="utf-8", dtype={"numero_cartao": str})
        lev = lev[lev["arquivo"].isin(files_df["arquivo"])]
        lev.to_parquet(bronze_dir / "labels_eventos.parquet", index=False)
        n_ev = len(lev)

    summary = {
        "arquivos": len(files), "com_erro": int(files_df["erro"].notna().sum()),
        "cartoes": int(files_df["card_id"].nunique()), "transacoes": n_tx,
        "admin_pendentes": n_adm, "rotulados": 0 if labels is None else len(labels),
        "eventos_rotulados": n_ev, "segundos": round(time.time() - t0, 1),
    }
    print("bronze OK:", summary)
    return summary


def main() -> None:
    cfg = config.pipeline_config()["ingest"]
    ap = argparse.ArgumentParser(description="raw .xlsx -> bronze parquet")
    ap.add_argument("--raw-dir", type=Path, default=config.path("raw_dir"))
    ap.add_argument("--bronze-dir", type=Path, default=config.path("bronze_dir"))
    ap.add_argument("--workers", type=int, default=min(cfg["workers"], os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=None, help="lê só os N primeiros arquivos (debug)")
    args = ap.parse_args()
    ingest(args.raw_dir.resolve(), args.bronze_dir, args.workers, cfg["part_size"],
           cfg["file_glob"], args.limit)


if __name__ == "__main__":
    main()
