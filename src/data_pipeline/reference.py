"""
Dimensões de referência (silver) a partir das bases oficiais do sistema:
linhas/tarifas, frota DETRAN e empresas empregadoras.

Reaproveita o carregador do gerador (mesma regra de join trajeto <-> código),
assim a tarifa "de tabela" usada na checagem de conluio é exatamente a das bases.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data_generator.viacard import config as vc_config
from src.data_generator.viacard.bases import carregar_bases


def build_dimensions(bases_dir: Path) -> dict[str, pd.DataFrame]:
    bases = carregar_bases(str(bases_dir))

    linhas = [{
        "operadora": l.operadora, "operador_display": l.display, "codigo_linha": l.codigo,
        "trajeto": l.trajeto, "tipo_linha": l.tipo, "tarifa_tabela": l.tarifa,
    } for ls in bases.linhas_por_operadora.values() for l in ls]
    dim_linha = (pd.DataFrame(linhas)
                 .drop_duplicates(["operador_display", "codigo_linha"])
                 .reset_index(drop=True))

    veiculos = []
    for op, frota in bases.frota_por_operadora.items():
        display = vc_config.OPERADORAS[op]["display"]
        veiculos += [{"operador_display": display, "veiculo": n, "tipo_rota": "MUNICIPAL"}
                     for n in frota.municipais]
        veiculos += [{"operador_display": display, "veiculo": n, "tipo_rota": "INTERMUNICIPAL"}
                     for n in frota.intermunicipais]
    dim_veiculo = pd.DataFrame(veiculos).drop_duplicates(["operador_display", "veiculo"])

    dim_empresa = pd.DataFrame([{"empresa": e.nome, "setor": e.setor,
                                 "perfil_financeiro": e.perfil_financeiro}
                                for e in bases.empresas])
    return {"dim_linha": dim_linha, "dim_veiculo": dim_veiculo, "dim_empresa": dim_empresa}
