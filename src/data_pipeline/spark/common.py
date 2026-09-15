"""
Utilitários compartilhados pelos notebooks Databricks.

Os notebooks rodam em dois lugares sem alteração:
  - Databricks: `spark` e `dbutils` já existem; parâmetros chegam por widgets
    (preenchidos pelo ADF em `baseParameters`); o lake é abfss://...;
  - local/Docker (validação): criamos uma SparkSession com Delta e os parâmetros
    vêm de variáveis de ambiente ou dos padrões.

Tabelas Delta são endereçadas por caminho (`<lake_root>/<camada>/<tabela>`), o que
funciona com e sem Unity Catalog. `register_table` cria o nome no metastore quando
um catálogo/esquema é informado.
"""
from __future__ import annotations

import os
from pathlib import Path


def _dbutils():
    try:
        import IPython

        return IPython.get_ipython().user_ns["dbutils"]
    except Exception:
        return None


def is_databricks() -> bool:
    return "DATABRICKS_RUNTIME_VERSION" in os.environ


def get_spark():
    from pyspark.sql import SparkSession

    active = SparkSession.getActiveSession()
    if active is not None:
        return active
    from delta import configure_spark_with_delta_pip

    builder = (SparkSession.builder.master(os.getenv("SPARK_MASTER", "local[*]"))
               .appName("smart-ticket-fraud")
               .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
               .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
               .config("spark.sql.session.timeZone", "UTC")
               .config("spark.ui.showConsoleProgress", "false")
               .config("spark.sql.shuffle.partitions", os.getenv("SPARK_SHUFFLE_PARTITIONS", "16"))
               .config("spark.driver.memory", os.getenv("SPARK_DRIVER_MEMORY", "6g")))
    return configure_spark_with_delta_pip(builder).getOrCreate()


def widget(name: str, default: str) -> str:
    """Parâmetro do notebook: widget no Databricks, variável de ambiente fora dele."""
    dbu = _dbutils()
    if dbu is not None:
        try:
            dbu.widgets.text(name, default)
            return dbu.widgets.get(name)
        except Exception:
            pass
    return os.getenv(name.upper(), default)


def repo_root() -> Path:
    p = Path.cwd().resolve()
    for cand in (p, *p.parents):
        if (cand / "mlops" / "pipeline.yml").exists():
            return cand
    raise RuntimeError("raiz do repositório não encontrada (mlops/pipeline.yml)")


def table_path(lake_root: str, layer: str, table: str) -> str:
    return f"{lake_root.rstrip('/')}/{layer}/{table}"


def write_delta(df, path: str, mode: str = "overwrite", partition_by: list[str] | None = None,
                replace_where: str | None = None) -> None:
    w = df.write.format("delta").mode(mode).option("overwriteSchema", "true")
    if replace_where:
        w = w.option("replaceWhere", replace_where)
    if partition_by:
        w = w.partitionBy(*partition_by)
    w.save(path)


def optimize(spark, path: str, zorder_by: list[str] | None = None) -> None:
    """Compacta arquivos pequenos e co-localiza por cartão (consulta típica: um cartão)."""
    z = f" ZORDER BY ({', '.join(zorder_by)})" if zorder_by else ""
    spark.sql(f"OPTIMIZE delta.`{path}`{z}")


def register_table(spark, catalog_schema: str, table: str, path: str) -> None:
    if catalog_schema:
        spark.sql(f"CREATE TABLE IF NOT EXISTS {catalog_schema}.{table} USING DELTA LOCATION '{path}'")
