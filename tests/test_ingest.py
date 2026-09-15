from src.data_generator.viacard.export import escrever_extrato
from src.data_pipeline.ingest import parse_workbook


def test_parse_extrato_gerado(passageiro_replay, tmp_path):
    path = escrever_extrato(passageiro_replay, str(tmp_path))
    out = parse_workbook(path)

    esperado = passageiro_replay.perfil.numero_cartao.replace(" ", "")
    assert out["card_id"] == esperado
    assert out["nome"] == passageiro_replay.perfil.nome
    assert len(out["tx"]) == len(passageiro_replay.eventos)
    assert len(out["admin"]) == len(passageiro_replay.admin)

    # a primeira linha do extrato é o evento mais recente
    mais_recente = max(passageiro_replay.eventos, key=lambda e: e.dt)
    ts, tipo, _, desc, *_ = out["tx"][0]
    assert ts == mais_recente.dt and desc == mais_recente.descricao and tipo == mais_recente.tipo


def test_parse_linhas_admin(passageiro_regular, tmp_path):
    out = parse_workbook(escrever_extrato(passageiro_regular, str(tmp_path)))
    for data, empresa, pedido, _, valor, _ in out["admin"]:
        assert empresa and pedido.isdigit() and valor > 0
