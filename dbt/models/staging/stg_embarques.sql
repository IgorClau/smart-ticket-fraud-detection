-- Um embarque (tipo USADO) por linha, com os sinais que a gold usa.
-- Regra de negócio: só embarque com débito gera receita; erro de leitura/gravação conta como erro;
-- "noite" é 20h-4h59 (mesma regra de src/feature_engineering/build.py).
select
    card_id,
    event_ts,
    cast(data as date)                                   as data,
    hora,
    operador_display,
    codigo_linha,
    tipo_linha,
    veiculo,
    sentido,
    is_debito,
    case when is_debito then vd else 0 end               as valor_debitado,
    (is_erro_leitura or is_erro_gravacao)                as is_erro,
    (hora >= 20 or hora < 5)                             as is_noite,
    tarifa_divergente,
    inconsistencia_saldo
from {{ source('silver', 'transactions') }}
where is_embarque
