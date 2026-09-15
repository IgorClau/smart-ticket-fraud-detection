"""
fraudes.py — MÓDULO 7 (v4.4): fraudes MATERIALIZADAS no extrato [24][25].

Na v4.3 as fraudes eram só uma marca interna sobre embarques normais: o extrato
exportado de um fraudador era idêntico ao de um usuário regular, e nenhum modelo
conseguia aprender nem ser avaliado. Aqui cada tipo do catálogo deixa uma
assinatura observável e plausível, organizada em EPISÓDIOS (janelas de dias). Cada
evento fraudulento carrega o rótulo `fraude`, exportado apenas em
`rotulos_eventos.csv` — nunca no .xlsx.

Assinaturas (o que muda no extrato):
  Venda de créditos ........ 2-4 embarques extras/dia em outra linha, horário comercial
  Empréstimo do cartão ..... ida/volta em dia de folga, em outra linha
  Endereço falso ........... recargas dimensionadas p/ tarifa declarada 1,5-2,2x maior (sobra saldo)
  Uso em férias ............ 15-30 dias sem rotina, com viagens intermunicipais de lazer
  Uso em licença ........... 2-5 meses sem rotina, com embarques esporádicos no meio do dia
  Desvio de finalidade ..... viagens noturnas (dia útil) ou de tarde (folga) em outra linha
  Clonagem ................. embarque em outra operadora minutos depois do legítimo (+ erro de leitura)
  Replay ................... mesma transação (linha, carro, sentido) repetida segundos depois
  Recarga clandestina ...... crédito sem pedido da empregadora, valor redondo, fora da dupla passada
  Uso offline .............. embarque NORMAL registrado sem débito no saldo
  Conluio operacional ...... tarifa abaixo da tabela, sempre no mesmo carro
  Uso de gratuidade + VT ... rotina some; outra pessoa usa o VT em outra linha no mesmo dia

Limite [24]: embarques fraudulentos <= 15% das utilizações (auditor, validação VF).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config
from .bases import Bases, Linha

# Embarques fraudulentos esperados por dia de episódio: converte a cota de
# eventos de cada tipo em dias de episódio.
TAXA_DIA = {
    "Venda de créditos": 1.8,
    "Empréstimo do cartão": 0.5,
    "Uso em férias": 2.0,
    "Uso em licença": 0.35,
    "Desvio de finalidade": 0.7,
    "Clonagem": 0.35,
    "Replay": 0.3,
    "Uso offline": 0.8,
    "Conluio operacional": 0.9,
    "Uso de gratuidade associado ao VT": 1.1,
}
# Probabilidade de o episódio "agir" num dia (episódios não são contínuos).
PROB_DIA = {
    "Venda de créditos": 0.6,
    "Empréstimo do cartão": 0.85,
    "Uso em férias": 1.0,
    "Uso em licença": 0.25,
    "Desvio de finalidade": 0.5,
    "Clonagem": 0.35,
    "Replay": 0.3,
    "Recarga clandestina": 0.08,
    "Uso offline": 0.55,
    "Conluio operacional": 0.65,
    "Uso de gratuidade associado ao VT": 0.6,
}
DURACAO = {
    "Uso em férias": (15, 30),
    "Uso em licença": (60, 150),
    "Endereço falso": (240, 720),
    "Recarga clandestina": (60, 240),
}
DURACAO_PADRAO = (14, 50)
# tipos que eliminam a rotina de trabalho durante TODO o episódio
SUPRIME_EPISODIO = {"Uso em férias", "Uso em licença"}
VALORES_CLANDESTINOS = [50, 60, 80, 100, 120, 150, 200]


@dataclass
class Episodio:
    tipo: str
    inicio: date
    fim: date
    linha: Linha | None = None      # linha usada pelo fraudador / terceiro
    carros: list = field(default_factory=list)
    operadora: str | None = None    # operadora da rotina no início (conluio)
    carro_fixo: int | None = None   # carro do motorista conivente
    mult: float = 1.0               # tarifa declarada (endereço falso) / desconto (conluio)
    empresa: str | None = None      # empresa fictícia da recarga clandestina


@dataclass
class PlanoFraude:
    episodios: list = field(default_factory=list)

    def ativos(self, d: date) -> list:
        return [e for e in self.episodios if e.inicio <= d <= e.fim]

    def mult_tarifa(self, d: date) -> float:
        """Multiplicador da tarifa declarada à empregadora (Endereço falso)."""
        m = 1.0
        for e in self.episodios:
            if e.tipo == "Endereço falso" and e.inicio <= d <= e.fim:
                m = max(m, e.mult)
        return m


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def carros_da_linha(bases: Bases, linha: Linha) -> list:
    fr = bases.frota_por_operadora[linha.operadora]
    return fr.carros(linha.tipo) or fr.municipais or fr.intermunicipais or [1]


def linha_alternativa(rng: random.Random, bases: Bases, atual: Linha, tipo: str,
                      prob_outra_operadora: float) -> Linha:
    ops = bases.operadoras_com_tipo(tipo)
    if rng.random() < prob_outra_operadora:
        cand = [o for o in ops if o != atual.operadora] or ops
    else:
        cand = [atual.operadora] if atual.operadora in ops else ops
    op = rng.choice(cand)
    linhas = [l for l in bases.linhas(op, tipo) if l.codigo != atual.codigo] or bases.linhas(op, tipo)
    return rng.choice(linhas)


def _epoca(trajetos: list, d: date):
    escolhido = trajetos[0]
    for t in trajetos:
        if t.inicio <= d:
            escolhido = t
    return escolhido


def _dt(rng: random.Random, d: date, minutos: float) -> datetime:
    hh, mm = divmod(int(minutos), 60)
    return datetime(d.year, d.month, d.day, min(hh, 23), mm, rng.randint(1, 59))


def _livre(acoes: list, dt: datetime, folga_min: float) -> bool:
    return all(abs((a["dt"] - dt).total_seconds()) >= folga_min * 60 for a in acoes)


def _horario(rng, d, acoes, ini_min, fim_min, folga_min=20.0, tentativas=12):
    for _ in range(tentativas):
        dt = _dt(rng, d, rng.uniform(ini_min, fim_min))
        if _livre(acoes, dt, folga_min):
            return dt
    return None


def acao(dt: datetime, linha: Linha, carro: int, direcao: str, fraude: str | None = None,
         tarifa: float | None = None, modo: str = "normal", status: str | None = None) -> dict:
    """Intenção de embarque consumida pelo motor de saldo."""
    return {"dt": dt, "desc": f"{linha.display} {carro} {linha.codigo} {direcao}",
            "tarifa": linha.tarifa if tarifa is None else tarifa,
            "fraude": fraude, "modo": modo, "status": status}


def _legitimos(acoes: list) -> list:
    return [a for a in acoes if a["fraude"] is None and a["modo"] == "normal"]


# --------------------------------------------------------------------------- #
# planejamento dos episódios
# --------------------------------------------------------------------------- #
def _posicionar(rng, ini: date, fim: date, dur: int, vacancias: list) -> date | None:
    span = (fim - ini).days - dur
    if span <= 0:
        return None
    for _ in range(25):
        inicio = ini + timedelta(days=rng.randint(0, span))
        termino = inicio + timedelta(days=dur - 1)
        if all(termino < v0 or inicio >= v1 for v0, v1 in vacancias):
            return inicio
    return None


def _configurar(rng: random.Random, ep: Episodio, trajetos: list, bases: Bases):
    tj = _epoca(trajetos, ep.inicio)
    atual = tj.linha
    ep.operadora = atual.operadora
    t = ep.tipo
    if t == "Uso em férias":
        ep.linha = linha_alternativa(rng, bases, atual, "INTERMUNICIPAL", 0.5)
    elif t == "Clonagem":
        ep.linha = linha_alternativa(rng, bases, atual, "MUNICIPAL", 1.0)
    elif t in ("Venda de créditos", "Empréstimo do cartão", "Desvio de finalidade",
               "Uso de gratuidade associado ao VT"):
        ep.linha = linha_alternativa(rng, bases, atual, "MUNICIPAL", 0.65)
    elif t == "Conluio operacional":
        ep.carro_fixo = rng.choice(tj.carros) if tj.carros else 1
        ep.mult = rng.choice([0.5, 0.6, 0.7])
    elif t == "Endereço falso":
        ep.mult = round(rng.uniform(1.5, 2.2), 2)
    elif t == "Recarga clandestina":
        empregadoras = {x.empresa.nome for x in trajetos}
        ep.empresa = rng.choice([e.nome for e in bases.empresas if e.nome not in empregadoras])
    if ep.linha is not None:
        ep.carros = carros_da_linha(bases, ep.linha)


def planejar(rng: random.Random, perfil, trajetos: list, vacancias: list, bases: Bases,
             usados_por_dia: float) -> PlanoFraude:
    plano = PlanoFraude()
    if not perfil.fraudes:
        return plano
    ini = perfil.data_emissao + timedelta(days=45)
    fim = perfil.data_fim - timedelta(days=5)
    dias = (fim - ini).days
    if dias < 180:
        return plano

    lo_i, hi_i = config.INTENSIDADE_FRAUDE[perfil.classe]
    cota_tipo = dias * usados_por_dia * rng.uniform(lo_i, hi_i) / len(perfil.fraudes)

    for tipo in perfil.fraudes:
        lo, hi = DURACAO.get(tipo, DURACAO_PADRAO)
        if tipo in TAXA_DIA:
            dias_alvo = cota_tipo / TAXA_DIA[tipo]
            n_ep = max(1, round(dias_alvo / ((lo + hi) / 2)))
        else:                                     # Endereço falso / Recarga clandestina
            dias_alvo, n_ep = None, 1
        for _ in range(n_ep):
            dur = rng.randint(lo, hi)
            if dias_alvo is not None and tipo not in SUPRIME_EPISODIO:
                dur = min(dur, max(7, int(dias_alvo)))
            inicio = _posicionar(rng, ini, fim, dur, vacancias)
            if inicio is None:
                continue
            ep = Episodio(tipo=tipo, inicio=inicio, fim=inicio + timedelta(days=dur - 1))
            _configurar(rng, ep, trajetos, bases)
            plano.episodios.append(ep)
    return plano


# --------------------------------------------------------------------------- #
# materialização diária
# --------------------------------------------------------------------------- #
def _venda(rng, ep, d, acoes, trabalhado, tj):
    for _ in range(rng.randint(2, 4)):
        dt = _horario(rng, d, acoes, 9 * 60 + 20, 21 * 60 + 30)
        if dt:
            acoes.append(acao(dt, ep.linha, rng.choice(ep.carros), rng.choice("IV"), ep.tipo))


def _emprestimo(rng, ep, d, acoes, trabalhado, tj):
    if trabalhado:
        return
    ida = _horario(rng, d, acoes, 8 * 60 + 30, 11 * 60 + 30)
    if not ida:
        return
    volta = ida + timedelta(minutes=rng.randint(180, 420), seconds=rng.randint(0, 59))
    if volta.date() != d or volta.hour >= 23 or not _livre(acoes, volta, 20):
        return
    acoes.append(acao(ida, ep.linha, rng.choice(ep.carros), "I", ep.tipo))
    acoes.append(acao(volta, ep.linha, rng.choice(ep.carros), "V", ep.tipo))


def _ferias(rng, ep, d, acoes, trabalhado, tj):
    for _ in range(rng.randint(1, 3)):
        dt = _horario(rng, d, acoes, 8 * 60, 20 * 60 + 30, folga_min=45)
        if dt:
            acoes.append(acao(dt, ep.linha, rng.choice(ep.carros), rng.choice("IV"), ep.tipo))


def _licenca(rng, ep, d, acoes, trabalhado, tj):
    ida = _horario(rng, d, acoes, 10 * 60, 12 * 60 + 30)
    if not ida:
        return
    acoes.append(acao(ida, tj.linha, rng.choice(tj.carros) if tj.carros else 1, "I", ep.tipo))
    if rng.random() < 0.6:
        volta = _horario(rng, d, acoes, 13 * 60 + 30, 16 * 60)
        if volta:
            acoes.append(acao(volta, tj.linha, rng.choice(tj.carros) if tj.carros else 1, "V", ep.tipo))


def _desvio(rng, ep, d, acoes, trabalhado, tj):
    ini, fim = (20 * 60 + 10, 23 * 60 + 20) if trabalhado else (13 * 60, 18 * 60 + 30)
    for _ in range(rng.randint(1, 2)):
        dt = _horario(rng, d, acoes, ini, fim)
        if dt:
            acoes.append(acao(dt, ep.linha, rng.choice(ep.carros), rng.choice("IV"), ep.tipo))


def _clonagem(rng, ep, d, acoes, trabalhado, tj):
    legit = _legitimos(acoes)
    if not legit:
        return
    r = rng.choice(legit)
    dt = r["dt"] + timedelta(seconds=rng.randint(180, 720))
    status = "ERRO DE LEITURA" if rng.random() < 0.35 else None
    acoes.append(acao(dt, ep.linha, rng.choice(ep.carros), rng.choice("IV"), ep.tipo, status=status))


def _replay(rng, ep, d, acoes, trabalhado, tj):
    legit = _legitimos(acoes)
    if not legit:
        return
    r = rng.choice(legit)
    dup = dict(r)
    dup["dt"] = r["dt"] + timedelta(seconds=rng.randint(25, 180))
    dup["fraude"] = ep.tipo
    acoes.append(dup)


def _clandestina(rng, ep, d, acoes, trabalhado, tj):
    dt = _horario(rng, d, acoes, 10 * 60, 19 * 60 + 30, folga_min=5)
    if dt:
        acoes.append({"dt": dt, "modo": "rec", "valor": float(rng.choice(VALORES_CLANDESTINOS)),
                      "empresa": ep.empresa, "pedido": str(rng.randint(100000, 999999)),
                      "fraude": ep.tipo, "status": None})


def _offline(rng, ep, d, acoes, trabalhado, tj):
    for r in _legitimos(acoes):
        if rng.random() < 0.6:
            r["modo"] = "offline"
            r["fraude"] = ep.tipo


def _conluio(rng, ep, d, acoes, trabalhado, tj):
    if tj.linha.operadora != ep.operadora:        # trocou de operadora: acabou o conluio
        return
    for r in _legitimos(acoes):
        partes = r["desc"].split()
        if partes[-2] != tj.linha.codigo or rng.random() > 0.7:
            continue
        r.update(acao(r["dt"], tj.linha, ep.carro_fixo, partes[-1], ep.tipo,
                      tarifa=round(tj.linha.tarifa * ep.mult, 2)))


def _gratuidade(rng, ep, d, acoes, trabalhado, tj):
    legit = _legitimos(acoes)
    if not trabalhado or not legit:
        return
    for r in legit:
        acoes.remove(r)                            # titular viaja de graça
    for r in legit:
        desloc = rng.choice([-1, 1]) * rng.randint(35, 110)
        dt = r["dt"] + timedelta(minutes=desloc, seconds=rng.randint(0, 59))
        if dt.date() == d and 5 <= dt.hour < 23 and _livre(acoes, dt, 20):
            acoes.append(acao(dt, ep.linha, rng.choice(ep.carros), r["desc"].split()[-1], ep.tipo))


_MATERIALIZADORES = {
    "Venda de créditos": _venda,
    "Empréstimo do cartão": _emprestimo,
    "Uso em férias": _ferias,
    "Uso em licença": _licenca,
    "Desvio de finalidade": _desvio,
    "Clonagem": _clonagem,
    "Replay": _replay,
    "Recarga clandestina": _clandestina,
    "Uso offline": _offline,
    "Conluio operacional": _conluio,
    "Uso de gratuidade associado ao VT": _gratuidade,
}


def materializar_dia(rng: random.Random, plano: PlanoFraude, d: date, acoes: list,
                     trabalhado: bool, tj) -> list:
    """Aplica os episódios ativos em `d` sobre as intenções legítimas do dia."""
    eps = plano.ativos(d)
    if not eps:
        return acoes
    if any(e.tipo in SUPRIME_EPISODIO for e in eps):
        acoes = []
    for ep in eps:
        fn = _MATERIALIZADORES.get(ep.tipo)
        if fn is not None and rng.random() < PROB_DIA[ep.tipo]:
            fn(rng, ep, d, acoes, trabalhado, tj)
    acoes.sort(key=lambda a: a["dt"])
    return acoes
