"""Contrato entre pipeline.yml, ADF, notebooks Databricks e deploy: o que um não pode citar sem o outro existir."""
import importlib.util
import json
import re

from src import config

ADF = config.ROOT / "mlops" / "adf"


def _atividades():
    pl = json.loads((ADF / "pipeline" / "pl_medallion_smart_ticket.json").read_text(encoding="utf-8"))
    return pl["properties"], [a for a in pl["properties"]["activities"] if a["type"] == "DatabricksNotebook"]


def test_estagios_do_pipeline_existem():
    for st in config.pipeline_config()["stages"]:
        assert importlib.util.find_spec(st["local"]) is not None, st["name"]
        if st["databricks_notebook"]:
            assert (config.ROOT / st["databricks_notebook"]).exists(), st["name"]
    assert "mlops/adf/pipeline/pl_medallion_smart_ticket.json" in (config.ROOT / "mlops" / "pipeline.yml").read_text(encoding="utf-8")


def test_parametros_do_adf_viram_widgets_nos_notebooks():
    props, notebooks = _atividades()
    assert len(notebooks) == 4
    for a in notebooks:
        caminho = a["typeProperties"]["notebookPath"]["value"]
        nome = re.search(r"/src/data_pipeline/spark/(\w+)'", caminho).group(1)
        codigo = (config.ROOT / "src" / "data_pipeline" / "spark" / f"{nome}.py").read_text(encoding="utf-8")
        for p, v in a["typeProperties"]["baseParameters"].items():
            assert f'widget("{p}"' in codigo, f"{nome} não lê o parâmetro {p}"
            for ref in re.findall(r"pipeline\(\)\.parameters\.(\w+)", v["value"]):
                assert ref in props["parameters"], f"{nome}: parâmetro {ref} não declarado no pipeline"


def test_placeholders_do_adf_sao_trocados_no_deploy():
    deploy = (config.ROOT / "mlops" / "infra" / "deploy.sh").read_text(encoding="utf-8")
    textos = "".join(p.read_text(encoding="utf-8") for p in ADF.glob("*/*.json"))
    for ph in set(re.findall(r"<[a-z-]+>", textos)):
        assert f"s#{ph}#" in deploy, f"deploy.sh não substitui {ph}"
    for fixo in ("stfdatalake", "adb-0000000000000000", "workspaces/dbw-smart-ticket-fraud"):
        if fixo in textos:
            assert fixo in deploy, f"deploy.sh não substitui {fixo}"


def test_registro_no_catalogo_e_neutro_sem_catalogo():
    # local/Docker: widget `catalog` vazio -> nada é registrado e o Spark nem é tocado
    from src.data_pipeline.spark.common import register_layer

    assert register_layer(None, "", "/lake", "silver", ["transactions"]) == []
