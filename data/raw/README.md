# data/raw — extratos brutos (não versionados)

Entrada do pipeline: um `.xlsx` por cartão, no layout do extrato ViaCard, mais os CSVs do gerador.

| Pasta | Conteúdo | Como obter |
|---|---|---|
| `viacard_v44/` | 2.500 extratos (lote de referência do case) + `manifesto.csv`, `rotulos.csv`, `rotulos_eventos.csv` | `python -m src.data_generator.run --n 2500 --seed 0 --overwrite` |
| `amostra_40/` | 40 extratos para testes rápidos e validação dos notebooks Spark | `python -m src.data_generator.run --n 40 --seed 0 --out data/raw/amostra_40` |

Os rótulos **nunca** estão dentro do `.xlsx` — só nos CSVs. O pipeline os carrega em tabelas
separadas (`labels_cartao`, `labels_eventos`) usadas apenas na avaliação.

Na nuvem, este papel é da zona `raw` do ADLS (`raw/extratos/ingest_date=AAAA-MM-DD/`), preenchida pelo ADF.
