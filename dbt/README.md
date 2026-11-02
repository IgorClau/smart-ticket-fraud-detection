# dbt — camada gold em SQL

Mesmos modelos em dois alvos (`profiles.yml`):

| Alvo | Motor | Fonte |
|---|---|---|
| `local` (padrão) | DuckDB | Parquet de `data/processed/silver` e `gold` |
| `azure` | Azure Databricks SQL Warehouse | tabelas Delta `silver.*` / `gold.*` |

```bash
cd dbt
dbt build --profiles-dir .
dbt docs generate --profiles-dir .
```

No Azure (variáveis `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN`):

```bash
dbt build --profiles-dir . --target azure
```

Camadas: `staging` (views 1:1 sobre a silver, só renomeia e deriva sinais) → `marts`
(fatos do BI, fila de auditoria, perguntas de negócio q01/q06/q10). Testes: genéricos
(`unique`, `not_null`, `relationships`, `accepted_values`, `nao_negativo`) e singulares
(paridade com a gold do Python, fila = 10% dos cartões).
