"""
Orquestrador local do pipeline medallion (espelho do pipeline do ADF).

Lê os estágios de mlops/pipeline.yml e executa em sequência. Cada estágio é um
módulo com `main()` próprio, então pode rodar isolado (é o que o ADF faz na nuvem,
chamando o notebook Databricks equivalente).

Uso:
    python -m src.pipeline                        # tudo
    python -m src.pipeline --from silver_transform
    python -m src.pipeline --only train_evaluate
"""
from __future__ import annotations

import argparse
import importlib
import sys
import time

from src import config


def run(from_stage: str | None = None, only: str | None = None) -> None:
    stages = config.pipeline_config()["stages"]
    nomes = [s["name"] for s in stages]
    for alvo in (from_stage, only):
        if alvo and alvo not in nomes:
            sys.exit(f"estágio desconhecido: {alvo}. Opções: {nomes}")
    if only:
        stages = [s for s in stages if s["name"] == only]
    elif from_stage:
        stages = stages[nomes.index(from_stage):]

    t0 = time.time()
    for i, st in enumerate(stages, 1):
        print(f"\n{'=' * 70}\n[{i}/{len(stages)}] {st['name']} — {st['description']}\n{'=' * 70}", flush=True)
        t = time.time()
        mod = importlib.import_module(st["local"])
        argv, sys.argv = sys.argv, [st["local"]]      # cada main() usa os padrões do pipeline.yml
        try:
            mod.main()
        finally:
            sys.argv = argv
        print(f"-> {st['name']} em {time.time() - t:.1f}s")
    print(f"\nPIPELINE OK em {time.time() - t0:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description="pipeline medallion local")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--from", dest="from_stage")
    g.add_argument("--only")
    args = ap.parse_args()
    run(args.from_stage, args.only)


if __name__ == "__main__":
    main()
