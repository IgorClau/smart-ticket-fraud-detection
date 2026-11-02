"""
Estágio dbt do pipeline: `dbt build` sobre a pasta dbt/ (marts SQL + testes, incluindo
paridade com a gold do Python).

O dbt vive num ambiente próprio (.venv-dbt, requirements-dbt.txt) porque fixa uma versão de
pydantic diferente da API. Este estágio procura o executável em DBT_EXE, depois em .venv-dbt
e por fim no PATH; se não achar, avisa e pula, para não bloquear o pipeline Python.
Local roda no alvo DuckDB; no Azure o mesmo projeto roda com `--target azure`
(Databricks SQL Warehouse).

Uso:
    python -m src.data_pipeline.dbt_run
    python -m src.data_pipeline.dbt_run --target azure
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from src import config

DBT_DIR = config.ROOT / "dbt"


def dbt_executavel() -> list[str] | None:
    if os.environ.get("DBT_EXE"):
        return [os.environ["DBT_EXE"]]
    # python -m em vez de dbt.exe: o lançador .exe do venv guarda o caminho absoluto e
    # quebra se a pasta do projeto for movida/renomeada; o python.exe do venv não.
    for rel in (".venv-dbt/Scripts/python.exe", ".venv-dbt/bin/python"):
        p = config.ROOT / rel
        if p.exists():
            return [str(p), "-m", "dbt.cli.main"]
    exe = shutil.which("dbt")
    return [exe] if exe else None


def main() -> None:
    ap = argparse.ArgumentParser(description="dbt build (marts + testes)")
    ap.add_argument("--target", default="local", choices=["local", "azure"])
    args = ap.parse_args()
    exe = dbt_executavel()
    if exe is None:
        print("dbt não encontrado — estágio pulado (python -m venv .venv-dbt && "
              ".venv-dbt/Scripts/pip install -r requirements-dbt.txt)")
        return
    cmd = [*exe, "build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR), "--target", args.target]
    if subprocess.run(cmd, cwd=DBT_DIR).returncode != 0:
        sys.exit("dbt build falhou: veja dbt/logs/dbt.log")


if __name__ == "__main__":
    main()
