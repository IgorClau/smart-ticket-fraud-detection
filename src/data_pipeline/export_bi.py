"""
Exporta a camada gold para o Power BI.

O Power BI Desktop lê Parquet nativamente (mais rápido e menor), mas às vezes é
preciso CSV — para abrir no Excel, mandar por e-mail ou usar um gateway antigo.
Este módulo resolve os dois casos e junta as tabelas que ficam particionadas por lote.

    python -m src.data_pipeline.export_bi --gold data/processed/lotes/consolidado/gold \
        --out data/processed/powerbi --formato csv --desde 2023-01-01

Uso típico com os 9 lotes: exportar tudo em parquet, e o fato diário só do período
que vai para o dashboard (o histórico completo tem dezenas de milhões de linhas).
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from src import config

# tabela -> coluna de data usada pelo filtro --desde (None = sem filtro)
TABELAS = {
    "card_scores": None,
    "card_features": None,
    "dim_linha": None,
    "fato_embarques_mensal": "ano_mes",
    "fato_embarques_diario": "data",
    "fato_recargas_mensal": "ano_mes",
}


def ler(gold: Path, nome: str) -> pd.DataFrame | None:
    """Lê a tabela como arquivo único ou como pasta particionada por lote."""
    arquivo, pasta = gold / f"{nome}.parquet", gold / nome
    if arquivo.exists():
        return pd.read_parquet(arquivo)
    if pasta.is_dir():
        partes = sorted(pasta.glob("*.parquet"))
        if partes:
            return pd.concat((pd.read_parquet(p) for p in partes), ignore_index=True)
    return None


def exportar(gold: Path, out: Path, formato: str, desde: str | None = None,
             tabelas: list[str] | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    resumo = {}
    for nome, col_data in TABELAS.items():
        if tabelas and nome not in tabelas:
            continue
        t0 = time.time()
        df = ler(gold, nome)
        if df is None:
            print(f"  (ausente) {nome}")
            continue
        if desde and col_data and col_data in df.columns:
            serie = df[col_data].astype(str) if col_data == "ano_mes" else pd.to_datetime(df[col_data]).dt.strftime("%Y-%m-%d")
            df = df[serie >= (desde[:7] if col_data == "ano_mes" else desde)]
        destino = out / f"{nome}.{formato}"
        if formato == "csv":
            # utf-8-sig e ponto decimal: abre no Excel em pt-BR sem remendo
            df.to_csv(destino, index=False, encoding="utf-8-sig")
        else:
            df.to_parquet(destino, index=False)
        mb = destino.stat().st_size / 1e6
        resumo[nome] = {"linhas": len(df), "MB": round(mb, 1)}
        print(f"  {nome:26} {len(df):>10,} linhas  {mb:>7.1f} MB  ({time.time() - t0:.1f}s)")
    print(f"pronto: {out}")
    return resumo


def main() -> None:
    ap = argparse.ArgumentParser(description="gold -> arquivos para o Power BI")
    ap.add_argument("--gold", type=Path, default=config.path("gold_dir"))
    ap.add_argument("--out", type=Path, default=config.ROOT / "data" / "processed" / "powerbi")
    ap.add_argument("--formato", choices=["parquet", "csv"], default="parquet")
    ap.add_argument("--desde", default=None, help="corta os fatos a partir desta data (AAAA-MM-DD)")
    ap.add_argument("--tabelas", nargs="*", default=None, help=f"subconjunto de {list(TABELAS)}")
    args = ap.parse_args()
    exportar(args.gold, args.out, args.formato, args.desde, args.tabelas)


if __name__ == "__main__":
    main()
