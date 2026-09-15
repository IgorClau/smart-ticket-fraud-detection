"""
Qualidade de dados da camada silver.

Contrato no estilo Great Expectations — cada checagem tem nome, observado,
esperado e severidade —, mas implementado em pandas puro: roda igual no CI,
nos testes e no notebook Databricks (a versão PySpark usa as mesmas regras).

Severidade:
  erro   -> o pipeline para (dado quebrado não pode chegar à gold)
  alerta -> registrado no relatório, o pipeline segue
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

TIPOS = {"USADO", "REC"}
STATUS = {"NORMAL", "ERRO DE LEITURA", "ERRO DE GRAVAÇÃO", "SALDO INSUFICIENTE"}
TETO_CARTAO = 1500.0


@dataclass
class Check:
    nome: str
    tabela: str
    ok: bool
    observado: str
    esperado: str
    severidade: str = "erro"

    def __post_init__(self):
        self.ok = bool(self.ok)          # numpy.bool_ -> bool (serializável em JSON)


class DataQualityError(RuntimeError):
    pass


def _pct(mask: pd.Series) -> float:
    return float(mask.mean()) if len(mask) else 0.0


def check_transactions(tx: pd.DataFrame) -> list[Check]:
    t = "silver.transactions"
    out: list[Check] = []

    def add(nome, falhas, esperado="0", severidade="erro"):
        n = int(falhas.sum()) if isinstance(falhas, pd.Series) else int(falhas)
        out.append(Check(nome, t, n == 0, str(n), esperado, severidade))

    add("card_id_nao_nulo", tx["card_id"].isna())
    add("event_ts_nao_nulo", tx["event_ts"].isna())
    add("tipo_no_dominio", ~tx["tipo"].isin(TIPOS))
    add("status_no_dominio", ~tx["status_emb"].isin(STATUS))
    add("vd_positivo", ~(tx["vd"] > 0))
    add("carteiras_nao_negativas", (tx["cart_a"] < -0.005) | (tx["cart_b"] < -0.005))
    add("saldo_ate_teto", tx["saldo"] > TETO_CARTAO + 0.01)

    debito = tx["is_debito"]
    add("dc_coerente", (debito & (tx["dc"] != "D")) | (tx["is_recarga"] & (tx["dc"] != "C"))
        | (tx["is_embarque"] & ~debito & tx["dc"].notna()))
    add("descricao_embarque_parseada", tx["is_embarque"] & tx["codigo_linha"].isna())
    add("descricao_recarga_parseada", tx["is_recarga"] & tx["empresa_recarga"].isna())
    add("sem_duplicatas", tx.duplicated(["card_id", "event_ts", "tipo", "descricao", "vd",
                                         "cart_a", "cart_b"]))
    add("cronologia_por_cartao", (tx.groupby("card_id")["event_ts"].diff().dt.total_seconds() < 0))
    add("ano_plausivel", ~tx["event_ts"].dt.year.between(2015, 2026))

    sem_linha = tx["is_embarque"] & tx["tipo_linha"].isna()
    out.append(Check("linha_existe_na_referencia", t, _pct(sem_linha) <= 0.001,
                     f"{_pct(sem_linha):.4%}", "<= 0.1%", "alerta"))
    sem_veic = tx["is_embarque"] & ~tx["veiculo_na_frota"]
    out.append(Check("veiculo_existe_na_frota", t, _pct(sem_veic) <= 0.001,
                     f"{_pct(sem_veic):.4%}", "<= 0.1%", "alerta"))
    return out


def check_cards(cards: pd.DataFrame, tx: pd.DataFrame, files: pd.DataFrame) -> list[Check]:
    out = [
        Check("card_id_unico", "silver.cards", not cards["card_id"].duplicated().any(),
              str(int(cards["card_id"].duplicated().sum())), "0"),
        Check("todo_cartao_tem_transacao", "silver.cards",
              cards["card_id"].isin(tx["card_id"].unique()).all(),
              str(int((~cards["card_id"].isin(tx["card_id"].unique())).sum())), "0"),
        Check("arquivos_lidos_sem_erro", "bronze.files", files["erro"].isna().all(),
              str(int(files["erro"].notna().sum())), "0", "alerta"),
    ]
    return out


def check_labels(labels: pd.DataFrame | None, cards: pd.DataFrame) -> list[Check]:
    if labels is None:
        return [Check("rotulos_presentes", "silver.labels_cartao", False, "ausente",
                      "presente", "alerta")]
    cobertura = cards["card_id"].isin(labels["card_id"]).mean()
    return [
        Check("rotulo_por_cartao_unico", "silver.labels_cartao",
              not labels["card_id"].duplicated().any(),
              str(int(labels["card_id"].duplicated().sum())), "0"),
        Check("cobertura_de_rotulos", "silver.labels_cartao", cobertura >= 0.95,
              f"{cobertura:.1%}", ">= 95%", "alerta"),
    ]


def enforce(checks: list[Check]) -> None:
    falhas = [c for c in checks if not c.ok and c.severidade == "erro"]
    if falhas:
        detalhe = "; ".join(f"{c.tabela}.{c.nome}: observado={c.observado}" for c in falhas)
        raise DataQualityError(f"{len(falhas)} checagem(ns) bloqueante(s) falharam: {detalhe}")


def write_report(checks: list[Check], path: Path) -> dict:
    rel = {
        "total": len(checks),
        "aprovadas": sum(c.ok for c in checks),
        "erros": sum((not c.ok) and c.severidade == "erro" for c in checks),
        "alertas": sum((not c.ok) and c.severidade == "alerta" for c in checks),
        "checks": [asdict(c) for c in checks],
    }
    path.write_text(json.dumps(rel, indent=2, ensure_ascii=False), encoding="utf-8")
    return rel
