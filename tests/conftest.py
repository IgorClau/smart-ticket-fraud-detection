"""Fixtures compartilhadas: bases de referência e extratos gerados em memória."""
from __future__ import annotations

import pandas as pd
import pytest

from src import config
from src.data_generator.viacard.bases import carregar_bases
from src.data_generator.viacard.motor import gerar_passageiro
from src.data_pipeline.reference import build_dimensions

BASES_DIR = config.ROOT / "data" / "synthetic" / "bases"


@pytest.fixture(scope="session")
def bases():
    return carregar_bases(str(BASES_DIR))


@pytest.fixture(scope="session")
def dims():
    return build_dimensions(BASES_DIR)


def passageiro_para_bronze(pas, card_id: str = "42.000000001-1") -> pd.DataFrame:
    """Converte os eventos do gerador no formato da bronze (ordem do extrato: mais recente no topo)."""
    eventos = sorted(pas.eventos, key=lambda e: e.dt, reverse=True)
    return pd.DataFrame([{
        "card_id": card_id, "event_ts": e.dt, "tipo": e.tipo, "status_emb": e.tipo_emb,
        "descricao": e.descricao, "cart_a": e.cart_a, "cart_b": e.cart_b, "dc": e.dc,
        "vd": e.vd, "_source_row": 10 + i,
    } for i, e in enumerate(eventos)]).astype({"event_ts": "datetime64[s]"})


def seed_com(bases, predicado, limite: int = 400) -> int:
    for s in range(limite):
        if predicado(gerar_passageiro(s, bases)):
            return s
    raise LookupError("nenhum seed satisfaz o predicado")


@pytest.fixture(scope="session")
def passageiro_regular(bases):
    return gerar_passageiro(seed_com(bases, lambda p: p.perfil.classe == "Regular"), bases)


@pytest.fixture(scope="session")
def passageiro_replay(bases):
    return gerar_passageiro(seed_com(bases, lambda p: "Replay" in p.perfil.fraudes
                                     and any(e.fraude == "Replay" for e in p.eventos)), bases)
