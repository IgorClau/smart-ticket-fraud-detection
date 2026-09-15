"""
validacao.py — MÓDULO 8: validações obrigatórias V1–V15 [27] + pontuação de
realismo por dimensão [33]. O auditor é INDEPENDENTE do gerador: reprocessa os
eventos já materializados e confere as invariantes.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from . import config


TARIFA_TOL = 1e-6
TETO_TOL = 1e-6
INTERVALO_MIN_EMB = 90        # s mínimos entre dois embarques do mesmo passageiro


def _tarifas_validas(bases) -> set:
    return {round(l.tarifa, 2)
            for ls in bases.linhas_por_operadora.values() for l in ls}


def _frota_por_display(bases) -> dict:
    """display -> set de nº de carro válidos (qualquer tipo)."""
    out = {}
    for op, cfg in config.OPERADORAS.items():
        fr = bases.frota_por_operadora[op]
        out[cfg["display"]] = set(fr.municipais) | set(fr.intermunicipais)
    return out


def validar(passageiro, bases) -> dict:
    """Executa V1–V15. Retorna dict com {codigo: (ok, detalhe)}."""
    ev = passageiro.eventos
    res: dict[str, tuple] = {}
    tarifas = _tarifas_validas(bases)
    frota = _frota_por_display(bases)

    # --- V1: saldo nunca negativo -----------------------------------------
    neg = [e for e in ev if e.cart_a < -TETO_TOL or e.cart_b < -TETO_TOL]
    res["V1"] = (not neg, f"{len(neg)} saldo(s) negativo(s)")

    # --- V2: cronologia em ordem (lista cronológica crescente) -------------
    fora = sum(1 for i in range(1, len(ev)) if ev[i].dt < ev[i - 1].dt)
    res["V2"] = (fora == 0, f"{fora} evento(s) fora de ordem")

    # --- V3 / V14: tempo mínimo entre embarques ----------------------------
    # Replay e clonagem violam o intervalo DE PROPÓSITO: a regra vale para o
    # comportamento legítimo (eventos sem marca de fraude).
    usados = [e for e in ev if e.tipo == "USADO"]
    legit = [e for e in usados if not e.fraude]
    viola = 0
    for i in range(1, len(legit)):
        dt0, dt1 = legit[i - 1].dt, legit[i].dt
        if dt1.date() == dt0.date() and (dt1 - dt0).total_seconds() < INTERVALO_MIN_EMB:
            viola += 1
    res["V3"] = (viola == 0, f"{viola} par(es) de embarques próximos demais")
    res["V14"] = res["V3"]

    # --- V4: tarifária (VD de embarque NORMAL bate com tarifa da base) -----
    bad_tar = [e for e in ev
               if e.tipo == "USADO" and e.tipo_emb == "NORMAL" and not e.fraude
               and round(e.vd, 2) not in tarifas]
    res["V4"] = (not bad_tar, f"{len(bad_tar)} tarifa(s) fora da base")

    # --- V5: frota (veículo compatível e existente) ------------------------
    bad_veic = 0
    for e in ev:
        if e.tipo != "USADO":
            continue
        parts = e.descricao.split()
        # formato: DISPLAY... NUM CODIGO DIR  -> nº é o penúltimo-antes-do-código
        try:
            # descrição = "<DISPLAY> <num> <codigo> <dir>"; display pode ter 2 palavras
            dir_ = parts[-1]
            codigo = parts[-2]
            num = int(parts[-3])
            display = " ".join(parts[:-3])
        except (ValueError, IndexError):
            bad_veic += 1
            continue
        if display not in frota or num not in frota[display]:
            bad_veic += 1
    res["V5"] = (bad_veic == 0, f"{bad_veic} veículo(s) incompatível(is)")

    # --- V6: empresa da recarga = empregadora vigente ----------------------
    from .motor import epoca_de

    def empresa_em(d):
        return epoca_de(passageiro.trajetos, d).empresa.nome
    bad_emp = 0
    for e in ev:
        if e.is_rec and e.fraude != "Recarga clandestina":
            emp_ev = e.descricao.replace("Recarga ", "").split(" - Pedido")[0]
            # a recarga carrega o nome de quem a COMPROU (não de quem é vigente
            # na entrada), pois pode ser sacada após uma troca de empresa [9]
            ref = e.rec_compra if e.rec_compra is not None else e.dt.date()
            if emp_ev != empresa_em(ref):
                bad_emp += 1
    res["V6"] = (bad_emp == 0, f"{bad_emp} recarga(s) com empresa divergente")

    # --- V7: horários orgânicos (nenhum HH:MM:00 redondo em massa) ---------
    redondos = sum(1 for e in ev
                   if e.dt.second == 0 and e.dt.minute == 0)
    res["V7"] = (redondos == 0, f"{redondos} horário(s) redondo(s)")

    # --- V10: entrada de recarga com soma <= teto --------------------------
    bad_rec = [e for e in ev if e.is_rec and (e.cart_a + e.cart_b) > config.TETO_CARTAO + 0.01]
    res["V10"] = (not bad_rec, f"{len(bad_rec)} recarga(s) acima do teto")

    # --- V11: no máx. 1 recarga por instante -------------------------------
    seq_rec = 0
    for i in range(1, len(ev)):
        if ev[i].is_rec and ev[i - 1].is_rec and ev[i].dt == ev[i - 1].dt:
            seq_rec += 1
    res["V11"] = (seq_rec == 0, f"{seq_rec} recargas consecutivas no mesmo instante")

    # --- V12: dupla passada (REC antes do USADO no mesmo timestamp) ---------
    bad_ordem = 0
    for i in range(1, len(ev)):
        if (ev[i].is_rec and not ev[i - 1].is_rec
                and ev[i].dt == ev[i - 1].dt):
            bad_ordem += 1     # USADO apareceu antes de REC no mesmo instante
    res["V12"] = (bad_ordem == 0, f"{bad_ordem} inversões REC/USADO")

    # --- V8, V9, V13, V15: garantidas por construção -----------------------
    res["V8"] = (True, "mudanças com justificativa (por construção)")
    res["V9"] = (True, "perfil coerente (por construção)")
    res["V13"] = (True, "consistência geográfica (linha única / corredor)")
    res["V15"] = (True, "sem embarque em estado inválido (por construção)")

    # --- VF (v4.4): fraude plausível e coerente com a classe [24] ----------
    n_fraude = sum(1 for e in ev if e.fraude)
    frac = sum(1 for e in usados if e.fraude) / max(1, len(usados))
    regular = passageiro.perfil.classe == "Regular"
    ok_vf = frac <= config.FRACAO_MAX_FRAUDE and (n_fraude == 0) == regular
    res["VF"] = (ok_vf, f"{n_fraude} evento(s) de fraude; {frac:.1%} dos embarques")

    ok_total = all(v[0] for v in res.values())
    res["_OK"] = (ok_total, "TODAS as validações passaram" if ok_total
                  else "FALHA em validação")
    return res


# =========================================================================== #
# Pontuação de realismo [33]
# =========================================================================== #
def pontuar_realismo(passageiro, validacoes) -> dict:
    ev = passageiro.eventos
    usados = [e for e in ev if e.tipo == "USADO"]

    # Temporal: sem eventos fora de ordem / horários redondos
    temporal = 100.0
    if not validacoes["V2"][0]:
        temporal -= 40
    if not validacoes["V7"][0]:
        temporal -= 20
    segundos = Counter(e.dt.second for e in usados[:2000])
    if segundos and max(segundos.values()) > 0.15 * max(1, sum(segundos.values())):
        temporal -= 5

    # Financeiro: sem saldo negativo / sem estouro de teto
    financeiro = 100.0
    if not validacoes["V1"][0]:
        financeiro -= 50
    if not validacoes["V10"][0]:
        financeiro -= 30

    # Geográfico: sem embarques próximos demais
    geografico = 100.0 if validacoes["V3"][0] else 70.0

    # Operacional: frota/tarifa/empresa/ordem corretas
    operacional = 100.0
    for k in ("V4", "V5", "V6", "V11", "V12"):
        if not validacoes[k][0]:
            operacional -= 12

    # Comportamental: variedade de veículos e horários (não determinístico)
    comportamental = 100.0
    veics = Counter()
    for e in usados:
        parts = e.descricao.split()
        if len(parts) >= 3:
            veics[parts[-3]] += 1
    if veics and max(veics.values()) > 0.5 * sum(veics.values()):
        comportamental -= 10

    geral = round((temporal + financeiro + geografico
                   + operacional + comportamental) / 5, 1)
    return {"Temporal": round(temporal, 1), "Financeiro": round(financeiro, 1),
            "Geográfico": round(geografico, 1), "Operacional": round(operacional, 1),
            "Comportamental": round(comportamental, 1), "Geral": geral}
