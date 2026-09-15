# Respostas às perguntas de negócio

Gerado por `python -m src.data_pipeline.sql.load_postgres --run` sobre o lote sintético v4.4.

## q01 — Quanto cada operadora transportou e faturou por ano?

_36 linha(s), 10.17s_

| operador_display   |   ano |   embarques_pagos |        receita |
|:-------------------|------:|------------------:|---------------:|
| VANGUARDA          |  2020 |            240945 |    1.41103e+06 |
| TRIBUZ             |  2020 |            230666 |    1.38347e+06 |
| PINHEIROS          |  2020 |            233826 |    1.37891e+06 |
| C DAS LIGAS        |  2020 |            218869 |    1.3067e+06  |
| ONTUR              |  2020 |            217423 |    1.26883e+06 |
| REZENDEZ           |  2020 |               281 | 3478.9         |
| VANGUARDA          |  2021 |            276068 |    1.61903e+06 |
| TRIBUZ             |  2021 |            268115 |    1.60829e+06 |
| PINHEIROS          |  2021 |            269120 |    1.58712e+06 |
| C DAS LIGAS        |  2021 |            255786 |    1.5274e+06  |
| ONTUR              |  2021 |            253314 |    1.46674e+06 |
| REZENDEZ           |  2021 |               491 | 6152.75        |
| TRIBUZ             |  2022 |            270268 |    1.62109e+06 |
| VANGUARDA          |  2022 |            267746 |    1.56863e+06 |
| C DAS LIGAS        |  2022 |            258375 |    1.54401e+06 |

## q02 — Quais as 10 linhas mais usadas em 2025 e quanto representam do total?

_10 linha(s), 3.40s_

| operador_display   | codigo_linha   | trajeto                                   |   embarques |   pct_total |   posicao |
|:-------------------|:---------------|:------------------------------------------|------------:|------------:|----------:|
| PINHEIROS          | PI200          | Circular Residencial Morada do Bosque     |       57802 |        5.91 |         1 |
| PINHEIROS          | PI203          | Três Poços x Ponte Alta (Radial Leste)    |       52969 |        5.42 |         2 |
| PINHEIROS          | PI201          | Conforto x Aero                           |       52549 |        5.38 |         3 |
| PINHEIROS          | PI202          | Nova Primavera x Ponte Alta (Municipal)   |       45896 |        4.7  |         4 |
| C DAS LIGAS        | 302            | Cacaria x Pirai (Mun Pirai)               |       13600 |        1.39 |         5 |
| C DAS LIGAS        | 312            | Ribeirao da Lajes x Pirai (Mun Pirai)     |       13539 |        1.39 |         6 |
| C DAS LIGAS        | 309            | Pirai x Sarole/Cruzeiro (Mun Pirai)       |       12094 |        1.24 |         7 |
| C DAS LIGAS        | 303            | Cacaria x Seropedica                      |       11728 |        1.2  |         8 |
| C DAS LIGAS        | 318            | Varjao x Pirai (Mun Pirai)                |       11009 |        1.13 |         9 |
| C DAS LIGAS        | 311            | Ponte das Laranjeiras x Pirai (Mun Pirai) |       10954 |        1.12 |        10 |

## q03 — Qual o horário de pico em dias úteis x fim de semana?

_20 linha(s), 10.49s_

|   hora |   dias_uteis |   fim_de_semana |
|-------:|-------------:|----------------:|
|      4 |          129 |              32 |
|      5 |        45035 |           14135 |
|      6 |      1382574 |          431714 |
|      7 |      1166497 |          367407 |
|      8 |        28873 |           10325 |
|      9 |        10133 |            7049 |
|     10 |        15585 |           10431 |
|     11 |        14172 |            8098 |
|     12 |        39741 |            4979 |
|     13 |        90627 |            5396 |
|     14 |        43166 |            6686 |
|     15 |        13260 |            7178 |
|     16 |       189345 |           62174 |
|     17 |      2256258 |          709521 |
|     18 |       265022 |           83252 |

## q04 — Como variou o volume mês a mês em 2025 (MoM)?

_13 linha(s), 1.54s_

| mes        |   embarques |   mes_anterior |   variacao_pct |   media_movel_3m |
|:-----------|------------:|---------------:|---------------:|-----------------:|
| 2024-12-01 |      104043 |            nan |          nan   |           104043 |
| 2025-01-01 |      100137 |         104043 |           -3.8 |           102090 |
| 2025-02-01 |      102089 |         100137 |            1.9 |           102090 |
| 2025-03-01 |      110853 |         102089 |            8.6 |           104360 |
| 2025-04-01 |      119995 |         110853 |            8.2 |           110979 |
| 2025-05-01 |      123844 |         119995 |            3.2 |           118231 |
| 2025-06-01 |      113438 |         123844 |           -8.4 |           119092 |
| 2025-07-01 |       80484 |         113438 |          -29.1 |           105922 |
| 2025-08-01 |       81707 |          80484 |            1.5 |            91876 |
| 2025-09-01 |       63183 |          81707 |          -22.7 |            75125 |
| 2025-10-01 |       47126 |          63183 |          -25.4 |            64005 |
| 2025-11-01 |       26050 |          47126 |          -44.7 |            45453 |
| 2025-12-01 |        8308 |          26050 |          -68.1 |            27161 |

## q05 — Quem são os 3 maiores usuários de cada operadora?

_20 linha(s), 2.63s_

| operador_display   |   posicao | nome                        |   embarques |
|:-------------------|----------:|:----------------------------|------------:|
| C DAS LIGAS        |         1 | GUSTAVO NOGUEIRA SANTOS     |        3999 |
| C DAS LIGAS        |         2 | LARISSA MOREIRA MARTINS     |        3790 |
| C DAS LIGAS        |         3 | OLÍVIA FERREIRA BARBOSA     |        3702 |
| ONTUR              |         1 | ANA MOREIRA SILVA           |        3779 |
| ONTUR              |         2 | ANA RIBEIRO RIBEIRO         |        3768 |
| ONTUR              |         3 | DIEGO APARECIDA COSTA       |        3721 |
| PINHEIROS          |         1 | LARISSA HENRIQUE PEREIRA    |        3851 |
| PINHEIROS          |         2 | DÉBORA FERREIRA LIMA        |        3757 |
| PINHEIROS          |         2 | OLÍVIA CARDOSO SOUZA        |        3757 |
| PINHEIROS          |         3 | OLÍVIA BARBOSA MARTINS      |        3732 |
| REZENDEZ           |         1 | CAMILA FERREIRA MENDES      |         102 |
| REZENDEZ           |         2 | GUSTAVO CRISTINA SOUZA      |          98 |
| REZENDEZ           |         3 | PAULO ALMEIDA OLIVEIRA      |          75 |
| REZENDEZ           |         3 | DIEGO NOGUEIRA OLIVEIRA     |          75 |
| TRIBUZ             |         1 | LUCAS DOS SANTOS NASCIMENTO |        3811 |

## q06 — Quais cartões repetem a MESMA transação em menos de 5 minutos (indício de replay)?

_10 linha(s), 13.02s_

| nome                       | card_id        |   repeticoes | menor_intervalo   |
|:---------------------------|:---------------|-------------:|:------------------|
| GUSTAVO NOGUEIRA SANTOS    | 42.980793003-7 |          301 | 0 days 00:00:04   |
| CAMILA NOGUEIRA NOGUEIRA   | 42.444371722-9 |          289 | 0 days 00:00:05   |
| NATHAN RIBEIRO ROCHA       | 42.737920166-9 |          242 | 0 days 00:00:09   |
| VINÍCIUS CARDOSO RIBEIRO   | 42.258254906-3 |          191 | 0 days 00:00:17   |
| VINÍCIUS MOREIRA RODRIGUES | 42.748567663-4 |          184 | 0 days 00:00:04   |
| EDUARDO CARVALHO RIBEIRO   | 42.342937748-0 |          183 | 0 days 00:00:16   |
| SÉRGIO TEIXEIRA MENDES     | 42.121551472-0 |          174 | 0 days 00:00:04   |
| RAFAELA CARDOSO RODRIGUES  | 42.479426166-5 |          173 | 0 days 00:00:23   |
| LARISSA GONÇALVES ROCHA    | 42.747239763-3 |          154 | 0 days 00:00:26   |
| JULIANA APARECIDA SANTOS   | 42.386036452-4 |          140 | 0 days 00:00:16   |

## q07 — Qual a maior sequência de dias seguidos com uso de cada cartão? (gaps and islands)

_15 linha(s), 0.15s_

| nome                      |   dias_seguidos | inicio     | fim        |
|:--------------------------|----------------:|:-----------|:-----------|
| RAFAELA BARBOSA RIBEIRO   |              20 | 2020-11-14 | 2020-12-03 |
| LARISSA CARDOSO COSTA     |               6 | 2021-04-18 | 2021-04-23 |
| MARIANA OLIVEIRA SILVA    |               6 | 2021-06-20 | 2021-06-25 |
| RAFAELA CARDOSO COSTA     |               6 | 2020-06-23 | 2020-06-28 |
| PRISCILA APARECIDA MENDES |              20 | 2024-04-02 | 2024-04-21 |
| GUSTAVO CARDOSO LIMA      |               6 | 2024-05-01 | 2024-05-06 |
| CAMILA GONÇALVES ROCHA    |               6 | 2024-08-12 | 2024-08-17 |
| JULIANA DE SOUZA RIBEIRO  |              27 | 2020-06-05 | 2020-07-01 |
| DIEGO BARBOSA COSTA       |              20 | 2024-10-03 | 2024-10-22 |
| LUCAS FERREIRA RODRIGUES  |              27 | 2024-03-09 | 2024-04-04 |
| FERNANDA TEIXEIRA COSTA   |              13 | 2021-06-08 | 2021-06-20 |
| RAFAELA NOGUEIRA SANTOS   |              27 | 2023-10-26 | 2023-11-21 |
| BRUNO CRISTINA NASCIMENTO |              13 | 2021-03-03 | 2021-03-15 |
| GUSTAVO MOREIRA MENDES    |               1 | 2020-04-16 | 2020-04-16 |
| RAFAELA CARDOSO COSTA     |              20 | 2021-12-31 | 2022-01-19 |

## q08 — Existem embarques NORMAL que não debitaram o saldo (validador offline)?

_10 linha(s), 16.33s_

| nome                        | card_id        |   embarques_sem_debito |   valor_nao_debitado |
|:----------------------------|:---------------|-----------------------:|---------------------:|
| TATIANE DOS SANTOS MENDES   | 42.805545706-9 |                    253 |               1490.9 |
| JULIANA ALMEIDA BARBOSA     | 42.958923188-1 |                    231 |               1362.9 |
| MARIANA DOS SANTOS NOGUEIRA | 42.660320895-0 |                    215 |               1268.7 |
| EDUARDO NOGUEIRA SOUZA      | 42.693149718-3 |                    192 |               1132.8 |
| YASMIN CRISTINA ROCHA       | 42.086894322-1 |                    189 |               1921.2 |
| EDUARDO CRISTINA MARTINS    | 42.410517299-1 |                    186 |               1097.4 |
| LARISSA TEIXEIRA SILVA      | 42.056341745-8 |                    175 |               1925   |
| FERNANDA BARBOSA SANTOS     | 42.585946945-2 |                    167 |               1002   |
| IGOR FERREIRA SILVA         | 42.969206946-8 |                    156 |                921.2 |
| MARCELO OLIVEIRA MENDES     | 42.282213091-7 |                    127 |                761.8 |

## q09 — Quais recargas entraram fora da dupla passada e com valor redondo?

_10 linha(s), 14.46s_

| nome                          | empresa_recarga     |   recargas_suspeitas |   valor |
|:------------------------------|:--------------------|---------------------:|--------:|
| EDUARDO DOS SANTOS CAVALCANTI | Edifica Brasil      |                   27 |    3130 |
| MARIANA OLIVEIRA CAVALCANTI   | MaxCompra           |                   25 |    2730 |
| CARLA ALMEIDA OLIVEIRA        | Ticket Fácil        |                   24 |    2670 |
| IGOR TEIXEIRA RIBEIRO         | Ponto da Moda       |                   23 |    2280 |
| RODRIGO BARBOSA ROCHA         | Mix Center          |                   22 |    2490 |
| IGOR CARDOSO BARBOSA          | Integra Supply      |                   22 |    2030 |
| OLÍVIA CARVALHO PEREIRA       | Ticket Fácil        |                   22 |    2370 |
| PAULO NOGUEIRA CAVALCANTI     | Central das Compras |                   22 |    2520 |
| RODRIGO APARECIDA NASCIMENTO  | Integra Obras       |                   22 |    2610 |
| HELENA GONÇALVES MARTINS      | Rota Sul Logística  |                   21 |    1940 |

## q10 — O score do modelo concentra fraude nos decis mais altos?

_10 linha(s), 0.02s_

|   decil |   cartoes |   fraudes |   taxa_fraude_pct |   recall_acumulado_pct |
|--------:|----------:|----------:|------------------:|-----------------------:|
|       1 |       250 |       246 |              98.4 |                   39.7 |
|       2 |       250 |       192 |              76.8 |                   70.8 |
|       3 |       250 |        89 |              35.6 |                   85.1 |
|       4 |       250 |        41 |              16.4 |                   91.8 |
|       5 |       250 |        16 |               6.4 |                   94.3 |
|       6 |       250 |        17 |               6.8 |                   97.1 |
|       7 |       250 |         5 |               2   |                   97.9 |
|       8 |       250 |         8 |               3.2 |                   99.2 |
|       9 |       250 |         3 |               1.2 |                   99.7 |
|      10 |       250 |         2 |               0.8 |                  100   |

## q11 — Em que perfil de cartão (cluster) a fraude se esconde?

_4 linha(s), 0.01s_

|   cluster |   cartoes |   taxa_fraude_pct |   score_medio |   em_alerta |
|----------:|----------:|------------------:|--------------:|------------:|
|         3 |       226 |             100   |        0.4929 |         153 |
|         1 |       311 |              27.7 |        0.4224 |          39 |
|         2 |       425 |              27.5 |        0.4156 |          42 |
|         0 |      1538 |              12.4 |        0.3732 |          16 |
