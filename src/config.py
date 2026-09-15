"""Leitura das configurações YAML e resolução de caminhos do projeto."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_CONFIG = ROOT / "mlops" / "pipeline.yml"
MODEL_CONFIG = ROOT / "mlops" / "model_config.yml"


@lru_cache(maxsize=None)
def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def pipeline_config() -> dict:
    return _load(PIPELINE_CONFIG)


def model_config() -> dict:
    return _load(MODEL_CONFIG)


def path(key: str) -> Path:
    """Caminho absoluto de uma entrada de `paths` do pipeline.yml."""
    p = Path(pipeline_config()["paths"][key])
    return p if p.is_absolute() else (ROOT / p).resolve()
