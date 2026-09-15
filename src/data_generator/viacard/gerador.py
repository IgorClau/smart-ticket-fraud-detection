"""
gerador.py — Orquestração (seção 30 do PROMPT MESTRE, v4.4).

Fluxo por extrato: gerar -> validar (V1–V15 + VF) -> pontuar realismo -> se falhar
qualquer validação OU realismo < corte, RE-SEMEAR e tentar de novo (até um teto
de tentativas). Tudo reprodutível a partir do seed base [29].

Saídas na pasta do lote:
- extrato_de_utilizacao_<nome>.xlsx : um por passageiro (sem nenhuma marca de fraude);
- manifesto.csv       : uma linha por extrato (seed, classe, escala, métricas);
- rotulos.csv         : rótulo por extrato (classe, is_fraude, tipos de fraude);
- rotulos_eventos.csv : v4.4 — uma linha por EVENTO fraudulento (ground truth fino).

Com --workers > 1 os extratos são gerados em processos paralelos; cada processo
carrega as bases uma única vez. O resultado não depende do nº de workers.
"""
from __future__ import annotations

import csv
import glob
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from . import config
from .bases import Bases, carregar_bases
from .motor import gerar_passageiro
from .validacao import validar, pontuar_realismo


@dataclass
class Resultado:
    seed: int
    passageiro: object
    validacoes: dict
    realismo: dict
    tentativas: int


def gerar_um(seed: int, bases: Bases, corte: float = config.CORTE_REALISMO,
             max_tentativas: int = 8) -> Resultado:
    """Gera um extrato válido, re-semeando se necessário [30]."""
    for t in range(max_tentativas):
        s = seed if t == 0 else seed * 1_000_003 + t      # reseed determinístico
        pas = gerar_passageiro(s, bases)
        val = validar(pas, bases)
        real = pontuar_realismo(pas, val)
        if val["_OK"][0] and real["Geral"] >= corte:
            return Resultado(seed=s, passageiro=pas, validacoes=val,
                             realismo=real, tentativas=t + 1)
    # devolve a última tentativa mesmo assim (marcada), para não travar o lote
    return Resultado(seed=s, passageiro=pas, validacoes=val,
                     realismo=real, tentativas=max_tentativas)


# --------------------------------------------------------------------------- #
# execução de um extrato (serve tanto ao modo sequencial quanto ao paralelo)
# --------------------------------------------------------------------------- #
_BASES: Bases | None = None


def _init_worker(base_dir: str):
    global _BASES
    _BASES = carregar_bases(base_dir)


def _processar(seed: int, out_dir: str) -> tuple[dict, list]:
    from .export import escrever_extrato        # import tardio (openpyxl)

    r = gerar_um(seed, _BASES)
    path = escrever_extrato(r.passageiro, out_dir)
    p = r.passageiro.perfil
    arquivo = os.path.basename(path)
    eventos = r.passageiro.eventos
    usados = [e for e in eventos if e.tipo == "USADO"]
    fraude_ev = [e for e in eventos if e.fraude]
    falhas = [k for k, v in r.validacoes.items() if not k.startswith("_") and not v[0]]
    linha = {
        "arquivo": arquivo,
        "seed": r.seed,
        "nome": p.nome,
        "numero_cartao": p.numero_cartao,
        "classe": p.classe,
        "escala": p.escala,
        "n_eventos": len(eventos),
        "n_recargas": sum(1 for e in eventos if e.is_rec),
        "n_admin_pendentes": len(r.passageiro.admin),
        "fraudes": "|".join(p.fraudes),
        "n_eventos_fraude": len(fraude_ev),
        "frac_embarques_fraude": round(sum(1 for e in usados if e.fraude) / max(1, len(usados)), 4),
        "n_episodios_fraude": len(r.passageiro.plano_fraude.episodios),
        "realismo_geral": r.realismo["Geral"],
        "validacoes_ok": r.validacoes["_OK"][0],
        "validacoes_falhas": "|".join(falhas),
        "tentativas": r.tentativas,
    }
    rotulos_ev = [{
        "arquivo": arquivo,
        "numero_cartao": p.numero_cartao,
        "event_ts": e.dt.isoformat(sep=" "),
        "tipo": e.tipo,
        "tipo_emb": e.tipo_emb,
        "descricao": e.descricao,
        "vd": round(e.vd, 2),
        "fraude": e.fraude,
    } for e in fraude_ev]
    return linha, rotulos_ev


def gerar_lote(base_dir: str, n: int, seed_inicial: int, out_dir: str,
               workers: int = 1, verbose: bool = True) -> list:
    """Gera `n` extratos, exporta XLSX e escreve manifesto + rótulos."""
    os.makedirs(out_dir, exist_ok=True)
    seeds = [seed_inicial + i for i in range(n)]
    manifesto: list[dict] = []
    rotulos_ev: list[dict] = []

    def registrar(i, linha, evs):
        manifesto.append(linha)
        rotulos_ev.extend(evs)
        if verbose and (not linha["validacoes_ok"] or (i + 1) % 50 == 0 or i + 1 == n):
            flag = "OK " if linha["validacoes_ok"] else "!! "
            print(f"[{i + 1:>5}/{n}] {flag}{linha['classe']:<11} ev={linha['n_eventos']:<5} "
                  f"fraude={linha['n_eventos_fraude']:<4} -> {linha['arquivo']}", flush=True)

    if workers <= 1:
        _init_worker(base_dir)
        for i, s in enumerate(seeds):
            registrar(i, *_processar(s, out_dir))
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(base_dir,)) as pool:
            for i, (linha, evs) in enumerate(pool.map(_processar, seeds,
                                                      [out_dir] * n, chunksize=4)):
                registrar(i, linha, evs)

    _escrever_csv(os.path.join(out_dir, "manifesto.csv"), manifesto)
    _escrever_csv(os.path.join(out_dir, "rotulos.csv"), [{
        "arquivo": m["arquivo"], "seed": m["seed"], "classe": m["classe"],
        "is_fraude": int(m["classe"] in ("Suspeito", "Fraudulento")),
        "tipos_fraude": m["fraudes"],
    } for m in manifesto])
    _escrever_csv(os.path.join(out_dir, "rotulos_eventos.csv"), rotulos_ev,
                  campos=["arquivo", "numero_cartao", "event_ts", "tipo", "tipo_emb",
                          "descricao", "vd", "fraude"])
    return manifesto


def limpar_lote(out_dir: str) -> int:
    """Remove extratos e CSVs de uma geração anterior na mesma pasta."""
    alvos = glob.glob(os.path.join(out_dir, "extrato_de_utilizacao_*.xlsx")) + \
        [os.path.join(out_dir, f) for f in ("manifesto.csv", "rotulos.csv", "rotulos_eventos.csv")]
    n = 0
    for f in alvos:
        if os.path.exists(f):
            os.remove(f)
            n += 1
    return n


def _escrever_csv(path: str, linhas: list, campos: list | None = None):
    campos = campos or (list(linhas[0].keys()) if linhas else [])
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)
