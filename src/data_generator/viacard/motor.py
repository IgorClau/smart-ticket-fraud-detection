"""
motor.py — MÓDULOS 1 a 7 do PROMPT MESTRE (v4.4).

Constrói, para UM passageiro, todo o histórico cronológico consistente:
perfil -> empresa -> trajeto -> cronologia -> recargas -> saldo -> fraudes.

O motor de saldo implementa a mecânica de dupla carteira observada no modelo:
- duas carteiras (A/B), soma <= R$1.500 [16][34.3];
- fila de recargas em FIFO [17];
- recarga entra quando a carteira de trabalho não cobre mais uma tarifa e a soma
  final não ultrapassa o teto [19]; dupla passada: REC vem ANTES do débito [19];
- só embarques NORMAL debitam [3]; erros e SALDO INSUFICIENTE não mexem no saldo;
- bloqueio de recarga > 18 meses trava as posteriores até desbloqueio [18].
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config
from . import fraudes as F
from .bases import Bases, Empresa, Linha


# =========================================================================== #
# estruturas
# =========================================================================== #
@dataclass
class Evento:
    """Uma linha do extrato (na ordem cronológica; export inverte)."""
    dt: datetime
    tipo: str            # "USADO" | "REC"
    tipo_emb: str        # NORMAL | ERRO DE LEITURA | ERRO DE GRAVAÇÃO | SALDO INSUFICIENTE
    descricao: str
    cart_a: float
    cart_b: float
    dc: str | None       # "D" | "C" | None
    vd: float
    is_rec: bool = False
    fraude: str | None = None   # marca interna (não vai para o extrato)
    rec_compra: date | None = None   # data da COMPRA da recarga (só p/ REC)


@dataclass
class Recarga:
    compra: date
    empresa: str
    pedido: str
    valor: float
    entrou: bool = False
    fraude: str | None = None   # compra dimensionada com fraude (Endereço falso)


@dataclass
class AdminEvento:
    data: date
    empresa: str
    pedido: str
    valor: float


@dataclass
class Perfil:
    seed: int
    nome: str
    numero_cartao: str
    idade: int
    escala: str
    classe: str                  # Regular | Suspeito | Fraudulento
    fraudes: list                # tipos de fraude aplicáveis
    habito_ida_offset: int       # deslocamento (min) do horário de ida
    habito_std_mult: float       # multiplicador de variância (ex.: "perde o ônibus")
    dia_extra: int | None        # weekday (0=seg) de viagem extra recorrente
    trabalha_fds: bool
    data_emissao: date
    data_fim: date
    lazer_prob_folga: float = 0.0    # v4.4: passeio legítimo em dia de folga
    intermun_prob_dia: float = 0.0   # v4.4: viagem intermunicipal eventual


# =========================================================================== #
# nomes sintéticos
# =========================================================================== #
_PRENOMES = ["Ana", "Bruno", "Carla", "Débora", "Eduardo", "Fernanda", "Gustavo",
             "Helena", "Igor", "Juliana", "Lucas", "Mariana", "Nathan", "Olívia",
             "Paulo", "Rafaela", "Sérgio", "Tatiane", "Vinícius", "Yasmin",
             "Camila", "Diego", "Larissa", "Marcelo", "Priscila", "Rodrigo"]
_MEIOS = ["Cristina", "Henrique", "Aparecida", "de Souza", "dos Santos", "Ferreira",
          "Oliveira", "Almeida", "Ribeiro", "Gonçalves", "Nogueira", "Barbosa",
          "Cardoso", "Teixeira", "Moreira", "Carvalho"]
_SOBRENOMES = ["Silva", "Santos", "Oliveira", "Souza", "Lima", "Costa", "Pereira",
               "Rodrigues", "Almeida", "Nogueira", "Araújo", "Ribeiro", "Martins",
               "Rocha", "Barbosa", "Nascimento", "Mendes", "Cavalcanti"]


def _gera_nome(rng: random.Random) -> str:
    partes = [rng.choice(_PRENOMES), rng.choice(_MEIOS), rng.choice(_SOBRENOMES)]
    return " ".join(partes).upper()


def _numero_cartao(rng: random.Random) -> str:
    corpo = rng.randint(0, 9_999_999_99)
    dv = rng.randint(0, 9)
    return f"42.{corpo:09d} - {dv}"


# =========================================================================== #
# utilidades de distribuição
# =========================================================================== #
def _escolha_ponderada(rng: random.Random, dist: dict):
    itens = list(dist.items())
    r = rng.random()
    acc = 0.0
    for k, p in itens:
        acc += p
        if r <= acc:
            return k
    return itens[-1][0]


def _lognormal(rng: random.Random, media: float, sigma: float) -> float:
    """Log-normal com MÉDIA aritmética `media` aproximada [26]."""
    mu = math.log(max(media, 1.0)) - sigma * sigma / 2.0
    return math.exp(rng.gauss(mu, sigma))


def _hora_do_dia(rng: random.Random, media_min: float, std_min: float) -> tuple[int, int, int]:
    m = int(round(rng.gauss(media_min, std_min)))
    m = max(4 * 60, min(23 * 60 + 30, m))     # dentro de um dia plausível
    hh, mm = divmod(m, 60)
    ss = rng.randint(0, 59)                    # segundos uniformes [21]
    return hh, mm, ss


# =========================================================================== #
# MÓDULO 1 — Perfil
# =========================================================================== #
def gerar_perfil(rng: random.Random, bases: Bases) -> Perfil:
    classe = _escolha_ponderada(rng, config.DIST_PERFIL_FRAUDE)
    fraudes = []
    if classe == "Fraudulento":
        fraudes = rng.sample(config.CATALOGO_FRAUDES, rng.randint(1, 3))
    elif classe == "Suspeito":
        fraudes = rng.sample(config.CATALOGO_FRAUDES, 1)

    escala = _escolha_ponderada(rng, config.DIST_ESCALA)
    if escala == "especial":
        escala = rng.choice(config.ESCALAS_ESPECIAIS)

    # janela temporal: fim ancorado em 2025, início ~5 anos antes (com jitter)
    fim_ano, fim_mes, fim_dia = config.DATA_FIM_PADRAO
    data_fim = date(fim_ano, fim_mes, fim_dia) - timedelta(days=rng.randint(0, 210))
    data_emissao = date(data_fim.year - config.ANOS_HISTORICO, 1, 1) \
        + timedelta(days=rng.randint(0, 120))

    return Perfil(
        seed=0,
        nome=_gera_nome(rng),
        numero_cartao=_numero_cartao(rng),
        idade=rng.randint(19, 63),
        escala=escala,
        classe=classe,
        fraudes=fraudes,
        habito_ida_offset=rng.choice([-25, -12, -5, 0, 5, 12]),   # chega cedo/tarde
        habito_std_mult=rng.choice([0.7, 1.0, 1.0, 1.4]),          # perde o ônibus
        dia_extra=rng.choice([None, None, None, 2, 4]),            # ex.: mercado 4ª
        trabalha_fds=rng.random() < 0.18,
        data_emissao=data_emissao,
        data_fim=data_fim,
    )


# =========================================================================== #
# MÓDULO 2 — Empresa empregadora (+ trajetória de mudanças) [9]
# =========================================================================== #
def gerar_empresas(rng: random.Random, bases: Bases, p: Perfil) -> list:
    tipo_mud = _escolha_ponderada(rng, config.DIST_MUDANCA_EMPRESA)
    if tipo_mud == "nunca":
        n_mud = 0
    elif tipo_mud == "uma":
        n_mud = 1
    else:
        n_mud = rng.randint(1, 8)

    empresas = rng.sample(bases.empresas, n_mud + 1)
    dias_total = (p.data_fim - p.data_emissao).days
    # pontos de corte ordenados para as trocas
    cortes = sorted(rng.sample(range(60, max(61, dias_total - 60)),
                               min(n_mud, max(0, dias_total - 121)))) if n_mud else []
    epocas = []
    inicio = p.data_emissao
    for i, emp in enumerate(empresas):
        fim = p.data_fim if i >= len(cortes) else p.data_emissao + timedelta(days=cortes[i])
        epocas.append((emp, inicio, fim))
        inicio = fim
        if i >= len(cortes):
            break
    return epocas


# =========================================================================== #
# MÓDULO 3 — Trajeto (linha, tarifa, veículos) [11]
# =========================================================================== #
@dataclass
class TrajetoEpoca:
    empresa: Empresa
    inicio: date
    fim: date
    linha: Linha
    carros: list
    linha_lazer: Linha | None = None   # v4.4: linha dos passeios de folga
    carros_lazer: list = field(default_factory=list)


def epoca_de(trajetos: list, d: date):
    """Época vigente em `d`: a ÚLTIMA cujo início <= d (resolve fronteiras)."""
    escolhido = trajetos[0]
    for t in trajetos:
        if t.inicio <= d:
            escolhido = t
    return escolhido


def gerar_trajetos(rng: random.Random, bases: Bases, epocas: list) -> list:
    # operadora do commuter: preferir quem tem linha MUNICIPAL (tarifa urbana)
    ops_mun = bases.operadoras_com_tipo("MUNICIPAL")
    out = []
    for emp, ini, fim in epocas:
        operadora = rng.choice(ops_mun)
        linhas_mun = bases.linhas(operadora, "MUNICIPAL")
        linha = rng.choice(linhas_mun)
        frota = bases.frota_por_operadora[operadora]
        carros = frota.carros(linha.tipo)
        out.append(TrajetoEpoca(empresa=emp, inicio=ini, fim=fim,
                                linha=linha, carros=carros))
    return out


# =========================================================================== #
# MÓDULO 4 — Cronologia (dias trabalhados + sazonalidade + vacância) [12][22][23.2]
# =========================================================================== #
def _dia_trabalhado(p: Perfil, d: date, dia_indice: int) -> bool:
    wd = d.weekday()  # 0=seg ... 6=dom
    if p.escala == "6x1":
        return (dia_indice % 7) != 6                 # 1 folga móvel a cada 7 dias
    if p.escala == "5x2":
        return wd < 5 or (p.trabalha_fds and wd == 5)
    if p.escala == "12x36":
        return (dia_indice % 2) == 0                 # 1 dia sim, 1 não
    if p.escala == "24x48":
        return (dia_indice % 3) == 0                 # 1 dia sim, 2 não
    return wd < 5


def _carnaval(ano: int) -> set:
    """Aproximação das datas de carnaval (dias sem uso) [23.2]."""
    tab = {2020: (2, 24), 2021: (2, 15), 2022: (2, 28), 2023: (2, 20),
           2024: (2, 12), 2025: (3, 3), 2026: (2, 16)}
    if ano not in tab:
        return set()
    m, d = tab[ano]
    base = date(ano, m, d)
    return {base + timedelta(days=k) for k in (-1, 0, 1)}


def gerar_vacancias(rng: random.Random, p: Perfil) -> list:
    """0-1 período de vacância (6-14 meses) para parte dos passageiros [22]."""
    if rng.random() > 0.22:
        return []
    dur = timedelta(days=30 * rng.randint(config.VACANCIA_MIN_MESES,
                                          config.VACANCIA_MAX_MESES))
    span = (p.data_fim - p.data_emissao).days
    if span < dur.days + 240:
        return []
    ini = p.data_emissao + timedelta(days=rng.randint(180, span - dur.days - 60))
    return [(ini, ini + dur)]


# =========================================================================== #
# MÓDULO 5 — Recargas (compras da empregadora) [14][23.1]
# =========================================================================== #
def _dia_util(d: date) -> bool:
    return d.weekday() < 5


def _nth_dia_util(ano: int, mes: int, n: int) -> date:
    d = date(ano, mes, 1)
    count = 0
    while True:
        if _dia_util(d):
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _ultimo_dia_util(ano: int, mes: int) -> date:
    if mes == 12:
        prox = date(ano + 1, 1, 1)
    else:
        prox = date(ano, mes + 1, 1)
    d = prox - timedelta(days=1)
    while not _dia_util(d):
        d -= timedelta(days=1)
    return d


def _data_recarga(rng: random.Random, perfil_fin: str, ano: int, mes: int) -> date:
    if perfil_fin == "industrial":
        return _nth_dia_util(ano, mes, config.DIA_UTIL_FIXO_INDUSTRIAL)
    if perfil_fin == "publica":
        return _ultimo_dia_util(ano, mes)
    if perfil_fin == "terceirizada":
        dia = rng.randint(3, 26)
        try:
            return date(ano, mes, dia)
        except ValueError:
            return _ultimo_dia_util(ano, mes)
    # comercial: fim de mês com variação
    base = _ultimo_dia_util(ano, mes)
    return base - timedelta(days=rng.randint(0, 5))


@dataclass
class GatilhoCompra:
    data: date
    empresa: str
    tarifa: float
    freq: int


def gerar_agenda_compras(rng: random.Random, trajetos: list, p: Perfil,
                         trips_mes_est: float) -> list:
    """Datas-gatilho mensais de compra por época [14][23.1].

    O VALOR de cada compra NÃO é fixado aqui: na timeline o RH completa o
    crédito disponível até um alvo (~1,8 mês), o que evita tanto o acúmulo
    irreal de recargas quanto a falta de saldo.
    """
    gatilhos: list[GatilhoCompra] = []
    for i_tj, tj in enumerate(trajetos):
        ultima = (i_tj == len(trajetos) - 1)
        limite_sup = tj.fim if ultima else tj.fim - timedelta(days=1)
        cur = date(tj.inicio.year, tj.inicio.month, 1)
        while cur <= tj.fim:
            ano, mes = cur.year, cur.month
            d = _data_recarga(rng, tj.empresa.perfil_financeiro, ano, mes)
            if d < tj.inicio:
                d = tj.inicio
            if d > limite_sup and not ultima:
                d = limite_sup
            if tj.inicio <= d <= limite_sup:
                freq = _escolha_ponderada(rng, config.DIST_FREQ_RECARGA)
                gatilhos.append(GatilhoCompra(data=d, empresa=tj.empresa.nome,
                                              tarifa=tj.linha.tarifa, freq=freq))
            cur = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    gatilhos.sort(key=lambda g: g.data)
    return gatilhos


# =========================================================================== #
# MÓDULO 6 — Saldo: engine de dupla carteira + FIFO + bloqueio 18m
# =========================================================================== #
class MotorSaldo:
    def __init__(self, recargas: list, rng: random.Random):
        self.fila = recargas                  # FIFO (ordenada por compra)
        self.rng = rng
        self.a = 0.0
        self.b = 0.0
        self.ativa = "b"                      # carteira em uso (modelo começa em B)
        self.eventos: list[Evento] = []
        self.idx_recarga = 0                  # ponteiro FIFO
        self.bloqueio_ativo = False

    # -- helpers de carteira --------------------------------------------------
    def _saldo(self):
        return self.a + self.b

    def _get(self, w):
        return self.a if w == "a" else self.b

    def _set(self, w, v):
        if w == "a":
            self.a = round(v, 2)
        else:
            self.b = round(v, 2)

    def _outra(self, w):
        return "b" if w == "a" else "a"

    # -- FIFO / bloqueio ------------------------------------------------------
    def _recarga_disponivel(self, dt: datetime):
        """Cabeça da fila comprada até `dt` e ainda não entrada [17]."""
        if self.bloqueio_ativo:
            return None
        if self.idx_recarga >= len(self.fila):
            return None
        rec = self.fila[self.idx_recarga]
        if rec.compra > dt.date():
            return None
        # bloqueio: cabeça esperando > 18 meses para entrar [18]
        limite = rec.compra + timedelta(days=int(config.BLOQUEIO_MESES * 30.44))
        if dt.date() > limite:
            self.bloqueio_ativo = True
            return None
        return rec

    def _tentar_entrada(self, dt: datetime, tarifa: float):
        """Dupla passada: credita 1 recarga na carteira drenada, se couber [19]."""
        rec = self._recarga_disponivel(dt)
        if rec is None:
            return
        # a carteira "baixa" é a que não cobre mais uma tarifa
        baixa = None
        if self._get(self.ativa) < tarifa:
            baixa = self.ativa
        elif self._get(self._outra(self.ativa)) < tarifa:
            baixa = self._outra(self.ativa)
        if baixa is None:
            return
        if self._saldo() + rec.valor > config.TETO_CARTAO + 1e-6:
            return                                # não estoura o teto [19][V10]
        novo = round(self._get(baixa) + rec.valor, 2)
        self._set(baixa, novo)
        rec.entrou = True
        self.idx_recarga += 1
        self.eventos.append(Evento(
            dt=dt, tipo="REC", tipo_emb="NORMAL",
            descricao=f"Recarga {rec.empresa} - Pedido {rec.pedido}",
            cart_a=self.a, cart_b=self.b, dc="C", vd=round(rec.valor, 2),
            is_rec=True, rec_compra=rec.compra, fraude=rec.fraude))
        # a carteira recém-carregada vira reserva; passa a drenar a outra
        self.ativa = self._outra(baixa)

    # -- embarque -------------------------------------------------------------
    def embarque(self, dt: datetime, tarifa: float, descricao: str,
                 forcar_status: str | None = None, fraude: str | None = None,
                 sem_debito: bool = False):
        # jamais horários redondos HH:MM:00 [21] — garante segundo >= 1
        if dt.second == 0:
            dt = dt.replace(second=self.rng.randint(1, 59))
        # 0) validador offline (fraude): registra NORMAL sem mexer no saldo
        if sem_debito:
            self.eventos.append(Evento(dt=dt, tipo="USADO", tipo_emb="NORMAL",
                                       descricao=descricao, cart_a=self.a,
                                       cart_b=self.b, dc="D", vd=tarifa,
                                       fraude=fraude))
            return
        # 1) dupla passada — entrada de recarga ANTES do débito [19][V12]
        self._tentar_entrada(dt, tarifa)

        # 2) erro de validador (sem débito) [3]
        status = forcar_status
        if status is None and self.rng.random() < config.PROB_ERRO_VALIDADOR:
            status = self.rng.choice(config.STATUS_ERRO)
        if status in config.STATUS_ERRO:
            self.eventos.append(Evento(dt=dt, tipo="USADO", tipo_emb=status,
                                       descricao=descricao, cart_a=self.a,
                                       cart_b=self.b, dc=None, vd=tarifa,
                                       fraude=fraude))
            return

        # 3) escolhe carteira que cobre a tarifa (prefere maior saldo)
        candidatas = [w for w in ("a", "b") if self._get(w) >= tarifa - 1e-6]
        if not candidatas:
            self.eventos.append(Evento(dt=dt, tipo="USADO",
                                       tipo_emb=config.STATUS_SEM_SALDO,
                                       descricao=descricao, cart_a=self.a,
                                       cart_b=self.b, dc=None, vd=tarifa,
                                       fraude=fraude))
            return
        w = max(candidatas, key=self._get)
        self._set(w, self._get(w) - tarifa)
        self.ativa = w
        self.eventos.append(Evento(dt=dt, tipo="USADO", tipo_emb="NORMAL",
                                   descricao=descricao, cart_a=self.a,
                                   cart_b=self.b, dc="D", vd=tarifa,
                                   fraude=fraude))

    # -- recarga clandestina (fraude): crédito sem pedido da empregadora -----
    def recarga_clandestina(self, dt: datetime, valor: float, empresa: str,
                            pedido: str, fraude: str):
        espaco = config.TETO_CARTAO - self._saldo()
        valor = min(valor, math.floor(espaco / 10) * 10)
        if valor < 20:
            return
        w = min(("a", "b"), key=self._get)
        self._set(w, self._get(w) + valor)
        self.eventos.append(Evento(
            dt=dt, tipo="REC", tipo_emb="NORMAL",
            descricao=f"Recarga {empresa} - Pedido {pedido}",
            cart_a=self.a, cart_b=self.b, dc="C", vd=round(valor, 2),
            is_rec=True, fraude=fraude))

    # -- compra dinâmica (gating na timeline) --------------------------------
    def pendentes(self) -> int:
        """Nº de recargas compradas e ainda não entradas (fila viva)."""
        return len(self.fila) - self.idx_recarga

    def valor_pendente(self) -> float:
        return sum(r.valor for r in self.fila[self.idx_recarga:])

    def comprar(self, rec: "Recarga"):
        """Efetiva uma compra: entra no fim da fila FIFO (ordem cronológica)."""
        self.fila.append(rec)

    # -- recargas não consumidas -> Lançamentos Administrativos [2][31] --------
    def recargas_pendentes(self) -> list:
        return [r for r in self.fila[self.idx_recarga:] if not r.entrou]


# =========================================================================== #
# construção dos "intents" de embarque (cronologia -> engine)
# =========================================================================== #
def _intents_dia(rng: random.Random, p: Perfil, tj: TrajetoEpoca, d: date) -> list:
    """Retorna lista de (datetime, direcao) para um dia trabalhado."""
    intents = []
    # ida (manhã)
    hh, mm, ss = _hora_do_dia(rng,
                              config.HORA_IDA_MEDIA_MIN + p.habito_ida_offset,
                              config.HORA_IDA_STD_MIN * p.habito_std_mult)
    intents.append((datetime(d.year, d.month, d.day, hh, mm, ss), "I"))
    # viagem extra recorrente (ex.: mercado) — antes da volta
    if p.dia_extra is not None and d.weekday() == p.dia_extra and rng.random() < 0.7:
        hh, mm, ss = _hora_do_dia(rng, 13 * 60 + 30, 40)
        intents.append((datetime(d.year, d.month, d.day, hh, mm, ss), "V"))
    # volta (fim de tarde)
    hh, mm, ss = _hora_do_dia(rng,
                              config.HORA_VOLTA_MEDIA_MIN,
                              config.HORA_VOLTA_STD_MIN * p.habito_std_mult)
    intents.append((datetime(d.year, d.month, d.day, hh, mm, ss), "V"))
    # eventual 3ª/4ª viagem esporádica (Poisson pequeno) [13][26]
    extra = _poisson(rng, 0.06)
    for _ in range(min(extra, 2)):
        hh, mm, ss = _hora_do_dia(rng, 19 * 60, 45)
        intents.append((datetime(d.year, d.month, d.day, hh, mm, ss), "V"))
    intents.sort(key=lambda x: x[0])
    # garante espaçamento mínimo entre embarques do mesmo dia [V3][V14]
    GAP = timedelta(minutes=15)
    for i in range(1, len(intents)):
        if intents[i][0] - intents[i - 1][0] < GAP:
            novo = intents[i - 1][0] + GAP + timedelta(seconds=rng.randint(30, 400))
            intents[i] = (novo, intents[i][1])
    return intents


def _poisson(rng: random.Random, lam: float) -> int:
    l = math.exp(-lam)
    k, prod = 0, 1.0
    while True:
        prod *= rng.random()
        if prod <= l:
            return k
        k += 1


# =========================================================================== #
# Hábitos legítimos de lazer (v4.4) [23]
# =========================================================================== #
def gerar_habitos_lazer(rng: random.Random, bases: Bases, p: Perfil, trajetos: list):
    """Passeios em folgas e viagens intermunicipais eventuais — comportamento
    legítimo que se parece com algumas fraudes e evita detecção trivial."""
    if rng.random() < config.PROB_TEM_LAZER:
        p.lazer_prob_folga = rng.uniform(*config.LAZER_PROB_FOLGA)
        for tj in trajetos:
            tj.linha_lazer = F.linha_alternativa(rng, bases, tj.linha, "MUNICIPAL", 0.4)
            tj.carros_lazer = F.carros_da_linha(bases, tj.linha_lazer)
    intermun = None
    if rng.random() < config.PROB_VIAGEM_INTERMUN:
        p.intermun_prob_dia = rng.randint(*config.VIAGENS_INTERMUN_ANO) / 365.0
        linha = F.linha_alternativa(rng, bases, trajetos[0].linha, "INTERMUNICIPAL", 0.5)
        intermun = (linha, F.carros_da_linha(bases, linha))
    return intermun


def _lazer_dia(rng: random.Random, p: Perfil, tj: TrajetoEpoca, d: date, intermun) -> list:
    if tj.linha_lazer is not None and rng.random() < p.lazer_prob_folga:
        linha, carros = tj.linha_lazer, tj.carros_lazer
    elif intermun is not None and rng.random() < p.intermun_prob_dia * 2.5:
        linha, carros = intermun                     # só em folgas: ~2,5x a taxa diária
    else:
        return []
    hh, mm, ss = _hora_do_dia(rng, 10 * 60 + 30, 70)
    ida = datetime(d.year, d.month, d.day, hh, mm, max(ss, 1))
    volta = ida + timedelta(minutes=rng.randint(150, 420), seconds=rng.randint(0, 59))
    if volta.date() != d or volta.hour >= 23:
        volta = datetime(d.year, d.month, d.day, 22, rng.randint(1, 50), rng.randint(1, 59))
    return [F.acao(ida, linha, rng.choice(carros), "I"),
            F.acao(volta, linha, rng.choice(carros), "V")]


# =========================================================================== #
# ORQUESTRAÇÃO de um passageiro
# =========================================================================== #
@dataclass
class Passageiro:
    perfil: Perfil
    eventos: list           # list[Evento] cronológico (oldest first)
    admin: list             # list[AdminEvento] (recargas pendentes)
    trajetos: list
    plano_fraude: F.PlanoFraude | None = None


def gerar_passageiro(seed: int, bases: Bases) -> Passageiro:
    rng = random.Random(seed)
    rng_h = random.Random(seed * 7_919 + 17)       # hábitos de lazer
    rng_f = random.Random(seed * 104_729 + 29)     # plano e materialização das fraudes
    p = gerar_perfil(rng, bases)
    p.seed = seed
    epocas = gerar_empresas(rng, bases, p)
    trajetos = gerar_trajetos(rng, bases, epocas)
    vacancias = gerar_vacancias(rng, p)
    intermun = gerar_habitos_lazer(rng_h, bases, p, trajetos)

    # estimativa de viagens/mês para dimensionar recargas
    dias_trab_semana = {"6x1": 6, "5x2": 5, "12x36": 3.5, "24x48": 2.3}.get(p.escala, 5)
    trips_mes_est = dias_trab_semana * 4.33 * 2

    plano = F.planejar(rng_f, p, trajetos, vacancias, bases,
                       usados_por_dia=dias_trab_semana / 7 * 2.1 * 0.93)
    agenda = gerar_agenda_compras(rng, trajetos, p, trips_mes_est)
    motor = MotorSaldo([], rng)             # fila cresce ao longo da timeline

    ALVO_MESES = 2.2      # RH completa o crédito disponível até ~2,2 meses [14]
    ptr = 0

    # cronologia dia-a-dia
    d = p.data_emissao
    dia_indice = 0
    while d <= p.data_fim:
        # 1) compras agendadas até hoje: completa o crédito disponível até o alvo.
        #    Endereço falso: a empregadora dimensiona pela tarifa DECLARADA.
        while ptr < len(agenda) and agenda[ptr].data <= d:
            g = agenda[ptr]
            ptr += 1
            saz = config.SAZONALIDADE_MES.get(g.data.month, 1.0)
            mult = plano.mult_tarifa(g.data)
            consumo_mes = trips_mes_est * g.tarifa * mult * saz
            disponivel = motor.a + motor.b + motor.valor_pendente()
            deficit = consumo_mes * ALVO_MESES - disponivel
            if deficit > 0.3 * consumo_mes:          # só compra se faltar de fato
                deficit = _lognormal(rng, deficit, 0.08)
                for k in range(g.freq):
                    valor = max(20.0, round(deficit / g.freq + rng.uniform(-3, 3), 2))
                    pedido = f"{rng.randint(100000, 999999)}"
                    motor.comprar(Recarga(compra=g.data, empresa=g.empresa,
                                          pedido=pedido, valor=valor,
                                          fraude="Endereço falso" if mult > 1 else None))

        em_vacancia = any(ini <= d < fim for ini, fim in vacancias)
        carnaval = d in _carnaval(d.year)
        tj = epoca_de(trajetos, d)
        acoes = []
        if (not em_vacancia and not carnaval
                and _dia_trabalhado(p, d, dia_indice)):
            saz = config.SAZONALIDADE_MES.get(d.month, 1.0)
            if rng.random() <= saz:      # sazonalidade reduz densidade de dias
                for dt, direcao in _intents_dia(rng, p, tj, d):
                    carro = rng.choice(tj.carros) if tj.carros else 1
                    acoes.append(F.acao(dt, tj.linha, carro, direcao))
        trabalhado = bool(acoes)
        if not em_vacancia:
            if not trabalhado and not carnaval:
                acoes = _lazer_dia(rng_h, p, tj, d, intermun)
            acoes = F.materializar_dia(rng_f, plano, d, acoes, trabalhado, tj)

        for a in acoes:
            if a["modo"] == "rec":
                motor.recarga_clandestina(a["dt"], a["valor"], a["empresa"],
                                          a["pedido"], a["fraude"])
            else:
                motor.embarque(a["dt"], a["tarifa"], a["desc"],
                               forcar_status=a["status"], fraude=a["fraude"],
                               sem_debito=a["modo"] == "offline")
        d += timedelta(days=1)
        dia_indice += 1

    # Lançamentos Administrativos = recargas compradas e ainda NÃO entradas [2]
    pend = motor.recargas_pendentes()
    admin = [AdminEvento(data=r.compra, empresa=r.empresa, pedido=r.pedido,
                         valor=r.valor) for r in pend]
    admin.sort(key=lambda a: a.data, reverse=True)      # mais recente no topo
    admin = admin[:6]                                    # buffer típico

    return Passageiro(perfil=p, eventos=motor.eventos, admin=admin,
                      trajetos=trajetos, plano_fraude=plano)
