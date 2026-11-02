-- Pergunta q01: quanto cada operadora transportou e faturou por ano.
select operador_display,
       extract(year from data)                      as ano,
       sum(n_debitos)                               as embarques_pagos,
       round(sum(valor_debitado), 2)                as receita
from {{ ref('fct_embarques_diario') }}
group by operador_display, extract(year from data)
