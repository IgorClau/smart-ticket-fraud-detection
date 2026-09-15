"""
export.py — MÓDULO 9: exportação do extrato em XLSX no layout EXATO do modelo
(`Extrato_Utilização_VC_...xlsx`) [31][34].

Fidelidade visual:
- fonte Segoe UI; moeda [$-416]#,##0.00; datas mm-dd-yy (admin) e m/d/yy h:mm (uso);
- cabeçalho com nome (merge B4:D4) e número do cartão (merge E4:J4);
- bloco "LANÇAMENTOS ADMINISTRATIVOS" (recargas disponíveis, verde);
- bloco "EXTRATO DE USO" em cronologia REVERSA (mais recente no topo);
- linhas REC destacadas em verde; SALDO como fórmula =CART_A+CART_B.

Desempenho (v4.4): os estilos são registrados UMA vez como NamedStyle e
atribuídos por nome. Criar Font/Fill/Alignment por célula fazia o openpyxl
hashear ~100 mil objetos por extrato (~4 s); por nome é uma cópia de tupla.
"""
from __future__ import annotations

import os
import re
import unicodedata

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, NamedStyle, PatternFill

# ---- paleta e formatos (extraídos do modelo) ------------------------------
FONTE = "Segoe UI"
MOEDA = "[$-416]#,##0.00"
FMT_DATA_ADMIN = "mm-dd-yy"
FMT_DATA_USO = "m/d/yy h:mm"

AZUL_TITULO_FILL = "FF9DC3E6"
AZUL_TEXTO = "FF1F3864"
VERDE_ADMIN_HDR = "FFA9D18E"
VERDE_ADMIN_FILL = "FFEAF5E4"
AZUL_COLHDR_FILL = "FFBDD7EE"
AZUL_USO_FILL = "FFEAF2FB"
VERDE_REC_FILL = "FFD9EAD3"
VERDE_REC_TEXTO = "FF2E6B2E"
CINZA_TEXTO = "FF1A1A1A"

LARGURAS = {"A": 2.43, "B": 19, "C": 10, "D": 21, "E": 34,
            "F": 13, "G": 13, "H": 7, "I": 11, "J": 14}

CABECALHOS = ["Data", "Tipo", "Tipo Emb.", "Descrição",
              "CART A", "CART B", "D/C", "VD", "SALDO"]

ESQ = Alignment(horizontal="left", vertical="center")
DIR = Alignment(horizontal="right")
CEN = Alignment(horizontal="center")


def _fill(cor):
    return PatternFill("solid", fgColor=cor)


def _sanitizar(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s.strip().lower()).strip("_")
    return s or "extrato"


def _registrar_estilos(wb: Workbook) -> None:
    def ns(nome, font=None, fill=None, align=None, fmt=None):
        s = NamedStyle(name=nome)
        if font is not None:
            s.font = font
        if fill is not None:
            s.fill = _fill(fill)
        if align is not None:
            s.alignment = align
        if fmt is not None:
            s.number_format = fmt
        wb.add_named_style(s)

    ns("vc_nome", Font(name=FONTE, size=13, bold=True, color=AZUL_TEXTO), AZUL_TITULO_FILL,
       Alignment(horizontal="left", vertical="center"))
    ns("vc_cartao", Font(name=FONTE, size=11, bold=True, color=AZUL_TEXTO), AZUL_TITULO_FILL,
       Alignment(horizontal="right", vertical="center"))
    ns("vc_faixa_azul", Font(name=FONTE, size=11, bold=True, color=AZUL_TEXTO), AZUL_TITULO_FILL, ESQ)
    ns("vc_faixa_verde", Font(name=FONTE, size=11, bold=True, color=AZUL_TEXTO), VERDE_ADMIN_HDR, ESQ)
    ns("vc_hdr", Font(name=FONTE, size=10, bold=True, color=AZUL_TEXTO), AZUL_COLHDR_FILL,
       Alignment(horizontal="center", vertical="center"))

    f_adm = Font(name=FONTE, size=10, color=CINZA_TEXTO)
    ns("vc_adm", f_adm, VERDE_ADMIN_FILL)
    ns("vc_adm_data", f_adm, VERDE_ADMIN_FILL, CEN, FMT_DATA_ADMIN)
    ns("vc_adm_txt", f_adm, VERDE_ADMIN_FILL, Alignment(horizontal="left"))
    ns("vc_adm_ct", f_adm, VERDE_ADMIN_FILL, CEN)
    ns("vc_adm_val", f_adm, VERDE_ADMIN_FILL, DIR, MOEDA)

    for k, fill, fonte, fonte_saldo in (
            ("uso", AZUL_USO_FILL, Font(name=FONTE, size=10, color=CINZA_TEXTO),
             Font(name=FONTE, size=10, bold=True, color=CINZA_TEXTO)),
            ("rec", VERDE_REC_FILL, Font(name=FONTE, size=10, bold=True, color=VERDE_REC_TEXTO),
             Font(name=FONTE, size=10, bold=True, color=VERDE_REC_TEXTO))):
        ns(f"vc_{k}_dt", fonte, fill, CEN, FMT_DATA_USO)
        ns(f"vc_{k}_ct", fonte, fill, CEN)
        ns(f"vc_{k}_txt", fonte, fill, Alignment(horizontal="left"))
        ns(f"vc_{k}_moeda", fonte, fill, DIR, MOEDA)
        ns(f"vc_{k}_saldo", fonte_saldo, fill, DIR, MOEDA)


def _faixa(ws, linha: int, texto: str, estilo: str) -> None:
    ws.merge_cells(f"B{linha}:J{linha}")
    for col in range(2, 11):
        ws.cell(linha, col).style = estilo
    ws.cell(linha, 2).value = texto


def escrever_extrato(passageiro, out_dir: str) -> str:
    p = passageiro.perfil
    wb = Workbook()
    _registrar_estilos(wb)
    ws = wb.active
    ws.title = "Extrato de Utilização"

    for col, w in LARGURAS.items():
        ws.column_dimensions[col].width = w

    # ---- cabeçalho (linha 4) ---------------------------------------------
    ws.merge_cells("B4:D4")
    ws.merge_cells("E4:J4")
    for col in range(2, 5):
        ws.cell(4, col).style = "vc_nome"
    for col in range(5, 11):
        ws.cell(4, col).style = "vc_cartao"
    ws["B4"].value = p.nome
    ws["E4"].value = f"Número do Cartão: {p.numero_cartao}"

    linha = 5
    # ---- bloco administrativo --------------------------------------------
    _faixa(ws, linha, "LANÇAMENTOS ADMINISTRATIVOS", "vc_faixa_verde")
    linha += 1

    estilos_adm = {2: "vc_adm_data", 3: "vc_adm_txt", 6: "vc_adm_ct", 9: "vc_adm_val"}
    for a in passageiro.admin:
        ws.merge_cells(f"C{linha}:E{linha}")
        ws.merge_cells(f"F{linha}:H{linha}")
        ws.merge_cells(f"I{linha}:J{linha}")
        for col in range(2, 11):
            ws.cell(linha, col).style = estilos_adm.get(col, "vc_adm")
        ws.cell(linha, 2).value = a.data
        ws.cell(linha, 3).value = a.empresa
        ws.cell(linha, 6).value = a.pedido
        ws.cell(linha, 9).value = round(a.valor, 2)
        linha += 1

    # ---- cabeçalho do extrato de uso -------------------------------------
    _faixa(ws, linha, "EXTRATO DE USO", "vc_faixa_azul")
    linha += 1

    # ---- linha de cabeçalhos de coluna -----------------------------------
    for i, titulo in enumerate(CABECALHOS):
        c = ws.cell(linha, 2 + i, titulo)
        c.style = "vc_hdr"
    linha += 1

    # ---- linhas de uso (cronologia reversa; REC acima do USADO em empate) --
    # sorted é estável: com reverse=True, empates preservam a ordem cronológica
    # de entrada (REC foi emitido antes do USADO), deixando REC no topo.
    eventos = sorted(passageiro.eventos, key=lambda e: e.dt, reverse=True)

    for e in eventos:
        k = "rec" if e.is_rec else "uso"
        valores = (
            (2, e.dt, f"vc_{k}_dt"),
            (3, e.tipo, f"vc_{k}_ct"),
            (4, e.tipo_emb, f"vc_{k}_ct"),
            (5, e.descricao, f"vc_{k}_txt"),
            (6, round(e.cart_a, 2), f"vc_{k}_moeda"),
            (7, round(e.cart_b, 2), f"vc_{k}_moeda"),
            (8, e.dc or "", f"vc_{k}_ct"),
            (9, round(e.vd, 2), f"vc_{k}_moeda"),
            # SALDO como FÓRMULA =CART_A + CART_B [skill xlsx]
            (10, f"=F{linha}+G{linha}", f"vc_{k}_saldo"),
        )
        for col, valor, estilo in valores:
            c = ws.cell(linha, col, valor)
            c.style = estilo
        linha += 1

    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "B4"

    os.makedirs(out_dir, exist_ok=True)
    fname = f"extrato_de_utilizacao_{_sanitizar(p.nome)}.xlsx"
    path = os.path.join(out_dir, fname)
    # evita colisão de nomes homônimos; a reserva atômica (O_EXCL) permite
    # vários processos gravando na mesma pasta
    base, ext = os.path.splitext(path)
    k = 2
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            path = f"{base}_{k}{ext}"
            k += 1
    wb.save(path)
    return path
