from src.data_generator.viacard import config as vc
from src.data_generator.viacard.motor import gerar_passageiro
from src.data_generator.viacard.validacao import validar


def test_regular_nao_tem_evento_de_fraude(passageiro_regular):
    assert not any(e.fraude for e in passageiro_regular.eventos)


def test_fraude_materializada_e_limitada(passageiro_replay, bases):
    usados = [e for e in passageiro_replay.eventos if e.tipo == "USADO"]
    fraude = [e for e in usados if e.fraude]
    assert fraude, "fraudador precisa ter eventos de fraude no extrato"
    assert len(fraude) / len(usados) <= vc.FRACAO_MAX_FRAUDE
    assert validar(passageiro_replay, bases)["_OK"][0]


def test_replay_repete_a_transacao_em_minutos(passageiro_replay):
    ev = passageiro_replay.eventos
    for i, e in enumerate(ev):
        if e.fraude == "Replay" and e.tipo_emb == "NORMAL":
            anteriores = [x for x in ev[:i] if x.descricao == e.descricao]
            assert anteriores and (e.dt - anteriores[-1].dt).total_seconds() <= 180
            return


def test_saldo_nunca_negativo_e_teto(passageiro_replay):
    for e in passageiro_replay.eventos:
        assert e.cart_a >= -1e-6 and e.cart_b >= -1e-6
        assert e.cart_a + e.cart_b <= vc.TETO_CARTAO + 0.01


def test_geracao_deterministica(bases):
    a, b = gerar_passageiro(123, bases), gerar_passageiro(123, bases)
    assert [(e.dt, e.descricao, e.vd, e.fraude) for e in a.eventos] == \
           [(e.dt, e.descricao, e.vd, e.fraude) for e in b.eventos]
