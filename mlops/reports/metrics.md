# Métricas do modelo

Cartões: **2500** · alertas (fila de auditoria): **250**

## Teste (30% dos cartões, estratificado)

| Modelo | ROC-AUC | PR-AUC | Precisão@fila | Recall@fila | Lift |
|---|---|---|---|---|---|
| Isolation Forest (produção) | 0.916 | 0.846 | 0.973 | 0.393 | 3.92 |
| LOF | 0.804 | 0.638 | 0.827 | 0.333 | 3.33 |
| Gradient Boosting supervisionado (teto) | 0.974 | 0.964 | 1.000 | 0.403 | 4.03 |

Prevalência de fraude no teste: 24.8% · fila de auditoria = 75 cartões.

Fila do tamanho da prevalência (quantos fraudadores cabem se revisarmos tantos cartões quanto o nº esperado de fraudes):

| Modelo | Precisão | Recall |
|---|---|---|
| Isolation Forest (produção) | 0.753 | 0.753 |
| LOF | 0.629 | 0.629 |
| Gradient Boosting supervisionado (teto) | 0.903 | 0.903 |

Recall na fila por classe real: {'Fraudulento': 0.451, 'Suspeito': 0.0}

## Perfis (KMeans, k=4)

|   cluster |   cartoes |   embarques_por_dia_ativo |   pct_dias_ativos |   pct_linha_principal |   n_linhas |   pct_fim_semana |   pct_noite |   pct_meio_dia |   maior_hiato_dias |   saldo_medio |   taxa_fraude |
|----------:|----------:|--------------------------:|------------------:|----------------------:|-----------:|-----------------:|------------:|---------------:|-------------------:|--------------:|--------------:|
|         0 |      1538 |                     2.064 |             0.804 |                 0.971 |          2 |            0.311 |       0.003 |          0.016 |                  6 |       143.558 |         0.124 |
|         1 |       311 |                     2.07  |             0.805 |                 0.354 |          9 |            0.305 |       0.003 |          0.027 |                  6 |       142.846 |         0.277 |
|         2 |       425 |                     2.07  |             0.44  |                 0.892 |          2 |            0.281 |       0.003 |          0.049 |                 10 |        84.664 |         0.275 |
|         3 |       226 |                     2.189 |             0.804 |                 0.898 |         10 |            0.307 |       0.008 |          0.049 |                  6 |       153.081 |         1     |
