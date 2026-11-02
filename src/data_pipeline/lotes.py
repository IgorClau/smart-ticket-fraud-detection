"""
Processamento de vários lotes de extratos (gerações independentes).

Cada lote vira uma partição própria — bronze, silver e gold separadas — e só o que é
pequeno (features por cartão, agregados) é consolidado no fim. Duas razões:

1. **Memória.** Os 9 lotes somam ~13,8 mil extratos (~37 M de transações). A silver de
   tudo junto não cabe em 16 GB; por lote, o pico é o do maior lote (~7 M de linhas).
2. **Identidade.** O mesmo número de cartão reaparece em lotes diferentes, com nome e
   histórico distintos. A silver resolve isso com a chave `lote:cartao`
   (`src/data_pipeline/silver.aplicar_chave_lote`).

Retomável: `--continuar` pula os lotes que já têm gold.

Uso:
    python -m src.data_pipeline.lotes --raw-dirs "C:/.../lote1" "C:/.../lote2" --continuar
    python -m src.data_pipeline.lotes --raw-dirs "C:/.../lote*" --so-consolidar
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import shutil
import time
from pathlib import Path

import pandas as pd

from src import config
from src.data_pipeline.ingest import ingest
from src.data_pipeline.silver import transform as silver_transform
from src.feature_engineering.build import build as gold_build, fato_embarques_mensal

CONSOLIDADO = "consolidado"


def processar_lote(raw_dir: Path, out_root: Path, workers: int, continuar: bool) -> dict:
    cfg = config.pipeline_config()["ingest"]
    lote = raw_dir.name
    base = out_root / lote
    gold = base / "gold"
    if continuar and (gold / "card_features.parquet").exists():
        print(f"[{lote}] já processado, pulando (--continuar)")
        return {"lote": lote, "status": "pulado"}

    t0 = time.time()
    print(f"\n{'=' * 70}\n[{lote}] {raw_dir}\n{'=' * 70}", flush=True)
    res_bronze = ingest(raw_dir, base / "bronze", workers, cfg["part_size"], cfg["file_glob"], lote=lote)
    res_silver = silver_transform(base / "bronze", base / "silver")
    res_gold = gold_build(base / "silver", gold, bi_tables=True)
    return {"lote": lote, "status": "ok", "arquivos": res_bronze["arquivos"],
            "com_erro": res_bronze["com_erro"], "transacoes": res_bronze["transacoes"],
            "rotulados": res_bronze["rotulados"], "cartoes": res_gold["cartoes"],
            "checks": res_silver["checks"], "segundos": round(time.time() - t0, 1)}


def _concat(arquivos: list[Path]) -> pd.DataFrame:
    return pd.concat([pd.read_parquet(f) for f in arquivos], ignore_index=True) if arquivos else pd.DataFrame()


def consolidar(out_root: Path, lotes: list[str]) -> dict:
    """Junta as saídas por lote no que o modelo e o Power BI consomem."""
    destino = out_root / CONSOLIDADO
    (destino / "gold").mkdir(parents=True, exist_ok=True)
    (destino / "silver").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    resumo: dict = {"lotes": lotes}

    # --- tabelas pequenas: uma linha por cartão -------------------------------
    for camada, nome in (("gold", "card_features"), ("silver", "cards"), ("silver", "labels_cartao")):
        arquivos = [out_root / l / camada / f"{nome}.parquet" for l in lotes]
        df = _concat([f for f in arquivos if f.exists()])
        if df.empty:
            continue
        dupes = int(df["card_id"].duplicated().sum())
        assert dupes == 0, f"{nome}: {dupes} card_id repetido entre lotes (chave por lote falhou)"
        df.to_parquet(destino / camada / f"{nome}.parquet", index=False)
        resumo[nome] = len(df)

    # dimensões são iguais em todos os lotes: basta uma
    for nome in ("dim_linha", "dim_veiculo", "dim_empresa"):
        origem = out_root / lotes[0] / "silver" / f"{nome}.parquet"
        if origem.exists():
            shutil.copy(origem, destino / "silver" / f"{nome}.parquet")
    shutil.copy(destino / "silver" / "dim_linha.parquet", destino / "gold" / "dim_linha.parquet")

    # --- fatos: mantidos particionados por lote (grandes demais p/ um arquivo) --
    for nome in ("fato_embarques_diario", "fato_recargas_mensal"):
        pasta = destino / "gold" / nome
        pasta.mkdir(exist_ok=True)
        linhas = 0
        for l in lotes:
            origem = out_root / l / "gold" / f"{nome}.parquet"
            if origem.exists():
                shutil.copy(origem, pasta / f"lote={l}.parquet")
                linhas += len(pd.read_parquet(origem, columns=["card_id"]))
        resumo[nome] = linhas

    # --- agregado mensal: fato leve, padrão do Power BI -------------------------
    mensais = []
    for l in lotes:
        origem = out_root / l / "gold" / "fato_embarques_diario.parquet"
        if not origem.exists():
            continue
        mensais.append(fato_embarques_mensal(pd.read_parquet(origem)))
    if mensais:
        mensal = pd.concat(mensais, ignore_index=True)
        mensal.to_parquet(destino / "gold" / "fato_embarques_mensal.parquet", index=False)
        resumo["fato_embarques_mensal"] = len(mensal)

    # --- qualidade: um relatório por lote vira um consolidado -------------------
    checks = []
    for l in lotes:
        rel = out_root / l / "silver" / "quality_report.json"
        if rel.exists():
            r = json.loads(rel.read_text(encoding="utf-8"))
            checks.append({"lote": l, "total": r["total"], "aprovadas": r["aprovadas"],
                           "erros": r["erros"], "alertas": r["alertas"],
                           "falhas": [c["nome"] for c in r["checks"] if not c["ok"]]})
    (destino / "qualidade_por_lote.json").write_text(json.dumps(checks, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    resumo["qualidade"] = {"lotes_ok": sum(c["erros"] == 0 for c in checks), "lotes": len(checks)}
    resumo["segundos"] = round(time.time() - t0, 1)
    print("consolidado OK:", {k: v for k, v in resumo.items() if k != "lotes"})
    return resumo


def main() -> None:
    ap = argparse.ArgumentParser(description="processa vários lotes e consolida")
    ap.add_argument("--raw-dirs", nargs="+", required=True,
                    help="pastas dos lotes (aceita curinga: 'C:/.../lote*')")
    ap.add_argument("--out", type=Path, default=config.ROOT / "data" / "processed" / "lotes")
    ap.add_argument("--workers", type=int, default=config.pipeline_config()["ingest"]["workers"])
    ap.add_argument("--continuar", action="store_true", help="pula lotes já processados")
    ap.add_argument("--so-consolidar", action="store_true", help="não processa, apenas consolida")
    args = ap.parse_args()

    dirs = sorted({Path(p) for padrao in args.raw_dirs for p in globmod.glob(padrao)},
                  key=lambda p: (len(p.name), p.name))
    dirs = [d for d in dirs if d.is_dir()]
    if not dirs:
        raise SystemExit(f"nenhuma pasta encontrada em {args.raw_dirs}")
    print(f"{len(dirs)} lote(s): {', '.join(d.name for d in dirs)}")

    t0 = time.time()
    linhas = []
    if not args.so_consolidar:
        for d in dirs:
            linhas.append(processar_lote(d, args.out, args.workers, args.continuar))

    consolidar(args.out, [d.name for d in dirs])
    if linhas:
        df = pd.DataFrame(linhas)
        df.to_csv(args.out / CONSOLIDADO / "resumo_lotes.csv", index=False)
        print("\n" + df.to_string(index=False))
    print(f"\nTOTAL em {(time.time() - t0) / 60:.1f} min · saída: {args.out / CONSOLIDADO}")
    print("Próximo passo: python -m src.training.train "
          f"--gold-dir {args.out / CONSOLIDADO / 'gold'} --silver-dir {args.out / CONSOLIDADO / 'silver'}")


if __name__ == "__main__":
    main()
