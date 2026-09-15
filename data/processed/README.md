# data/processed — lakehouse local (medallion)

Gerado por `python -m src.pipeline`. Só `gold/card_scores.parquet` é versionado (entra na imagem da API).

```
bronze/   transactions/ admin_pendentes/ (part-files)  files  labels  labels_eventos
silver/   transactions  cards  recargas_pendentes  dim_linha  dim_veiculo  dim_empresa
          labels_cartao  labels_eventos  quality_report.json
gold/     card_features  card_scores  fato_embarques_diario  fato_recargas_mensal  dim_linha
lakehouse/  mesmas camadas em Delta Lake, produzidas pelos notebooks Spark (validação local)
```

| Camada | Regra |
|---|---|
| bronze | fiel ao arquivo; só nomes de coluna e metadados de origem |
| silver | tipado, deduplicado, parseado, enriquecido com referência; checagens de qualidade bloqueantes |
| gold | pronto para consumo: 1 linha por cartão (modelo/API) e agregados (Power BI) |
