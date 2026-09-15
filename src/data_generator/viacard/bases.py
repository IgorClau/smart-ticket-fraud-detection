"""
bases.py — MÓDULO 0: carregamento das bases obrigatórias [5].

Regra de ouro: usar EXCLUSIVAMENTE os arquivos anexados; nunca inventar
tarifa, linha, veículo ou empresa. Os loaders são tolerantes às pequenas
variações de cabeçalho encontradas entre operadoras (linha do header e nome
da aba mudam de arquivo para arquivo).
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field

import openpyxl

from . import config


# --------------------------------------------------------------------------- #
# utilidades
# --------------------------------------------------------------------------- #
def _norm(s) -> str:
    """Normaliza para JOIN por nome: sem acento, caixa alta, espaços colapsados."""
    if s is None:
        return ""
    s = str(s).strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def _tipo_rota(v) -> str:
    """Padroniza 'Municipal'/'Intermunicipal' -> 'MUNICIPAL'/'INTERMUNICIPAL'."""
    n = _norm(v)
    return "INTERMUNICIPAL" if "INTER" in n else "MUNICIPAL"


# --------------------------------------------------------------------------- #
# estruturas de dados
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Linha:
    operadora: str        # chave canônica (ex.: "Pinheiros")
    display: str          # nome exibido no extrato (ex.: "PINHEIROS")
    trajeto: str          # nome do trajeto
    codigo: str           # código de itinerário (ex.: "PI200")
    tarifa: float
    tipo: str             # MUNICIPAL / INTERMUNICIPAL


@dataclass
class Frota:
    operadora: str
    # nº do carro -> tipo de rota
    municipais: list = field(default_factory=list)
    intermunicipais: list = field(default_factory=list)

    def carros(self, tipo: str) -> list:
        return self.intermunicipais if tipo == "INTERMUNICIPAL" else self.municipais


@dataclass
class Empresa:
    nome: str
    setor: str
    perfil_financeiro: str   # industrial / terceirizada / publica / comercial


@dataclass
class Bases:
    linhas_por_operadora: dict          # operadora -> list[Linha]
    frota_por_operadora: dict           # operadora -> Frota
    empresas: list                      # list[Empresa]
    empresas_por_perfil: dict           # perfil -> list[Empresa]

    def linhas(self, operadora: str, tipo: str | None = None) -> list:
        ls = self.linhas_por_operadora[operadora]
        return [l for l in ls if tipo is None or l.tipo == tipo]

    def operadoras_com_tipo(self, tipo: str) -> list:
        return [op for op, ls in self.linhas_por_operadora.items()
                if any(l.tipo == tipo for l in ls)]


# --------------------------------------------------------------------------- #
# loaders individuais
# --------------------------------------------------------------------------- #
def _achar_header(ws, alvo: str, max_scan: int = 8) -> int:
    """Retorna a linha (1-index) cujo conteúdo contém `alvo` (normalizado)."""
    alvo_n = _norm(alvo)
    for r in range(1, min(ws.max_row, max_scan) + 1):
        for c in range(1, ws.max_column + 1):
            if _norm(ws.cell(r, c).value) == alvo_n:
                return r
    return -1


def _load_trajetos(path: str) -> dict:
    """{trajeto_normalizado: (nome_original, tarifa, tipo)}."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    hdr = _achar_header(ws, "TRAJETO")
    out = {}
    if hdr < 0:
        return out
    for r in range(hdr + 1, ws.max_row + 1):
        traj = ws.cell(r, 2).value
        tar = ws.cell(r, 3).value
        tipo = ws.cell(r, 6).value
        if traj is None or tar is None:
            continue
        if _norm(traj).startswith("TOTAL"):
            continue
        try:
            tar = float(tar)
        except (TypeError, ValueError):
            continue
        out[_norm(traj)] = (str(traj).strip(), tar, _tipo_rota(tipo))
    return out


def _load_codigos(path: str) -> dict:
    """{trajeto_normalizado: (codigo, tipo)}."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Códigos de Linha"] if "Códigos de Linha" in wb.sheetnames else wb.active
    hdr = _achar_header(ws, "TRAJETO DA LINHA")
    out = {}
    if hdr < 0:
        return out
    for r in range(hdr + 1, ws.max_row + 1):
        traj = ws.cell(r, 1).value
        cod = ws.cell(r, 2).value
        tipo = ws.cell(r, 3).value
        if traj is None or cod is None:
            continue
        if _norm(traj).startswith("TOTAL"):
            continue
        out[_norm(traj)] = (str(cod).strip(), _tipo_rota(tipo))
    return out


def _load_frota(path: str, operadora: str) -> Frota:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Matrículas"] if "Matrículas" in wb.sheetnames else wb.active
    hdr = _achar_header(ws, "Nº do Carro")
    fr = Frota(operadora=operadora)
    if hdr < 0:
        return fr
    for r in range(hdr + 1, ws.max_row + 1):
        num = ws.cell(r, 1).value
        tipo = ws.cell(r, 3).value
        status = ws.cell(r, 4).value
        if num is None:
            continue
        if status is not None and _norm(status) not in ("ATIVO", ""):
            continue
        try:
            num = int(num)
        except (TypeError, ValueError):
            continue
        if _tipo_rota(tipo) == "INTERMUNICIPAL":
            fr.intermunicipais.append(num)
        else:
            fr.municipais.append(num)
    return fr


# --------------------------------------------------------------------------- #
# empresas [5]
# --------------------------------------------------------------------------- #
_SETOR_RE = re.compile(r"^\s*\d+\.\s+(.+?)\s*\(\d+-\d+\)\s*$")
_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")


def _load_empresas(path: str) -> list:
    empresas: list[Empresa] = []
    setor_atual = None
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or set(line.strip()) <= {"-", "="}:
                continue
            m_setor = _SETOR_RE.match(line)
            if m_setor:
                setor_atual = m_setor.group(1).strip().upper()
                continue
            m_item = _ITEM_RE.match(line)
            if m_item and setor_atual:
                nome = m_item.group(2).strip()
                if nome.upper().startswith(("LISTA ", "SETOR")):
                    continue
                perfil = config.SETOR_PERFIL_FINANCEIRO.get(setor_atual, "comercial")
                empresas.append(Empresa(nome=nome, setor=setor_atual,
                                        perfil_financeiro=perfil))
    return empresas


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def carregar_bases(base_dir: str) -> Bases:
    """Carrega e junta todas as bases a partir de `base_dir`."""
    linhas_por_operadora: dict[str, list] = {}
    frota_por_operadora: dict[str, Frota] = {}

    for operadora, cfg in config.OPERADORAS.items():
        traj = _load_trajetos(os.path.join(base_dir, cfg["traj"]))
        cod = _load_codigos(os.path.join(base_dir, cfg["cod"]))
        frota = _load_frota(os.path.join(base_dir, cfg["mat"]), operadora)

        linhas = []
        for chave, (nome, tarifa, tipo_t) in traj.items():
            if chave not in cod:
                continue                    # sem código -> descarta (V4)
            codigo, tipo_c = cod[chave]
            tipo = tipo_c or tipo_t
            linhas.append(Linha(operadora=operadora, display=cfg["display"],
                                trajeto=nome, codigo=codigo, tarifa=tarifa,
                                tipo=tipo))
        if not linhas:
            raise ValueError(f"Operadora {operadora}: nenhuma linha carregada.")
        linhas_por_operadora[operadora] = linhas
        frota_por_operadora[operadora] = frota

    empresas = _load_empresas(os.path.join(base_dir,
                                           "Lista_150_empresas_organizadas.txt"))
    if not empresas:
        raise ValueError("Nenhuma empresa carregada da lista de 150.")

    por_perfil: dict[str, list] = {}
    for e in empresas:
        por_perfil.setdefault(e.perfil_financeiro, []).append(e)

    return Bases(linhas_por_operadora=linhas_por_operadora,
                 frota_por_operadora=frota_por_operadora,
                 empresas=empresas, empresas_por_perfil=por_perfil)
