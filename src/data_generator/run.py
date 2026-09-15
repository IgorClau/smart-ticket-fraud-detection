"""
CLI do gerador de extratos sintéticos ViaCard (v4.4).

Exemplos (a partir da raiz do repositório):
    # lote de referência do case: 2.500 extratos, 7 processos
    python -m src.data_generator.run --n 2500 --seed 0 --workers 7 --overwrite

    # amostra pequena para testes
    python -m src.data_generator.run --n 20 --seed 1000 --out data/raw/amostra
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

from src.data_generator.viacard.gerador import gerar_lote, limpar_lote

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description="Gerador de extratos ViaCard v4.4")
    ap.add_argument("--n", type=int, default=5, help="quantidade de extratos")
    ap.add_argument("--seed", type=int, default=0, help="seed inicial (reprodutível)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "raw" / "viacard_v44")
    ap.add_argument("--bases", type=Path, default=ROOT / "data" / "synthetic" / "bases",
                    help="diretório com os 19 arquivos-base")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--overwrite", action="store_true",
                    help="apaga extratos e rótulos de uma geração anterior em --out")
    ap.add_argument("--quiet", action="store_true", help="menos logs")
    args = ap.parse_args()

    if not args.bases.is_dir():
        sys.exit(f"ERRO: diretório de bases inexistente: {args.bases}")
    existentes = list(args.out.glob("extrato_de_utilizacao_*.xlsx")) if args.out.exists() else []
    if existentes:
        if not args.overwrite:
            sys.exit(f"ERRO: {args.out} já tem {len(existentes)} extratos. Use --overwrite.")
        print(f"Removidos {limpar_lote(str(args.out))} arquivos da geração anterior.")

    t0 = time.time()
    print(f"Gerando {args.n} extrato(s) (seed inicial {args.seed}, {args.workers} worker(s)) "
          f"em {args.out} ...")
    manifesto = gerar_lote(str(args.bases), n=args.n, seed_inicial=args.seed,
                           out_dir=str(args.out), workers=args.workers,
                           verbose=not args.quiet)

    dt = time.time() - t0
    ok = sum(1 for m in manifesto if m["validacoes_ok"])
    classes = Counter(m["classe"] for m in manifesto)
    n_ev = sum(m["n_eventos_fraude"] for m in manifesto)
    print(f"\nConcluído: {len(manifesto)} extrato(s) em {dt:.1f}s "
          f"({dt / max(1, len(manifesto)):.2f}s/extrato)")
    print(f"  válidos: {ok}/{len(manifesto)} | classes: {dict(classes)} | eventos de fraude: {n_ev}")
    print(f"  saída: {args.out} (manifesto.csv, rotulos.csv, rotulos_eventos.csv)")


if __name__ == "__main__":
    main()
