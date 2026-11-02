-- Recargas (tipo REC): crédito pedido pela empregadora.
select
    card_id,
    event_ts,
    ano_mes,
    empresa_recarga,
    pedido,
    vd as valor_recarga
from {{ source('silver', 'transactions') }}
where is_recarga
