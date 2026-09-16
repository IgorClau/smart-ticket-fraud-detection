"""Regras que só aparecem ao processar gerações antigas lado a lado (lotes 1-9)."""
import pandas as pd
import pytest

from src.data_pipeline.silver import (aplicar_chave_lote, canonizar_operadora, canonizar_status,
                                      separar_quarentena, transform_transactions)


def _bronze(linhas: list[dict], card_id="42.000000001-1", lote=None) -> pd.DataFrame:
    base = {"tipo": "USADO", "status_emb": "NORMAL", "descricao": "C DAS LIGAS 12 310 I",
            "cart_a": 100.0, "cart_b": 0.0, "dc": "D", "vd": 6.0}
    df = pd.DataFrame([{**base, **linha} for linha in linhas])
    df["card_id"] = card_id
    df["event_ts"] = pd.date_range("2024-03-01 07:00:00", periods=len(df), freq="7h")
    df["_source_row"] = range(len(df), 0, -1)
    if lote:
        df["lote"] = lote
    return df


def test_chave_por_lote_separa_cartoes_homonimos():
    a = aplicar_chave_lote(_bronze([{}], lote="lote1"))
    b = aplicar_chave_lote(_bronze([{}], lote="lote9"))
    assert a["card_id"].iloc[0] == "lote1:42.000000001-1"
    assert set(a["card_id"]) & set(b["card_id"]) == set()
    assert a["card_id_origem"].iloc[0] == "42.000000001-1"


def test_sem_coluna_lote_nada_muda():
    df = _bronze([{}])
    assert aplicar_chave_lote(df)["card_id"].iloc[0] == "42.000000001-1"


def test_status_sem_acento_vira_canonico():
    tx = canonizar_status(_bronze([{"status_emb": "ERRO DE GRAVACAO"}, {"status_emb": "NORMAL"}]))
    assert tx["status_emb"].tolist() == ["ERRO DE GRAVAÇÃO", "NORMAL"]


def test_operadora_sem_espacos_casa_com_a_referencia(dims):
    tx = _bronze([{"descricao": "CDASLIGAS 12 310 I"}])
    tx["operador_display"] = "CDASLIGAS"
    assert canonizar_operadora(tx, dims["dim_linha"])["operador_display"].iloc[0] == "C DAS LIGAS"


def test_silver_enriquece_extrato_antigo(dims):
    """Descrição no formato antigo tem de sair com tipo de linha e veículo válido."""
    linha = dims["dim_linha"].query("operador_display == 'C DAS LIGAS'").iloc[0]
    veic = dims["dim_veiculo"].query("operador_display == 'C DAS LIGAS'")["veiculo"].iloc[0]
    desc = f"CDASLIGAS {veic} {linha.codigo_linha} I"
    tx = transform_transactions(_bronze([{"descricao": desc, "vd": linha.tarifa_tabela}]), dims)
    assert tx["operador_display"].iloc[0] == "C DAS LIGAS"
    assert tx["tipo_linha"].iloc[0] == linha.tipo_linha
    assert bool(tx["veiculo_na_frota"].iloc[0]) and not bool(tx["tarifa_divergente"].iloc[0])


@pytest.mark.parametrize("defeito,motivo", [
    ({"vd": 0.0, "dc": None}, "embarque_sem_tarifa"),
    ({"cart_a": 1400.0, "cart_b": 300.0}, "saldo_acima_do_teto"),
])
def test_quarentena_remove_cartao_defeituoso(dims, defeito, motivo):
    bom = transform_transactions(_bronze([{}, {}], card_id="bom"), dims)
    ruim = transform_transactions(_bronze([{}, defeito], card_id="ruim"), dims)
    tx, quarentena = separar_quarentena(pd.concat([bom, ruim], ignore_index=True))

    assert set(tx["card_id"]) == {"bom"}, "o cartão íntegro continua no pipeline"
    assert quarentena["card_id"].tolist() == ["ruim"]
    assert motivo in quarentena["motivos"].iloc[0]
    assert quarentena["linhas_afetadas"].iloc[0] >= 1


def test_sem_defeito_nao_ha_quarentena(dims):
    tx = transform_transactions(_bronze([{}, {}]), dims)
    limpo, quarentena = separar_quarentena(tx)
    assert len(limpo) == len(tx) and quarentena.empty
