-- Pergunta q06: mesma transação (linha, carro, sentido) repetida em menos de 5 minutos = indício de replay.
with seq as (
    select card_id, event_ts, codigo_linha, veiculo, sentido,
           lag(event_ts)     over (partition by card_id order by event_ts) as ts_anterior,
           lag(codigo_linha) over (partition by card_id order by event_ts) as linha_anterior,
           lag(veiculo)      over (partition by card_id order by event_ts) as veiculo_anterior,
           lag(sentido)      over (partition by card_id order by event_ts) as sentido_anterior
    from {{ ref('stg_embarques') }}
)
select card_id, count(*) as repeticoes
from seq
where codigo_linha = linha_anterior
  and veiculo = veiculo_anterior
  and sentido = sentido_anterior
  and event_ts < ts_anterior + interval 5 minute
group by card_id
