select card_id, ano_mes, empresa_recarga,
       count(*)           as n_recargas,
       sum(valor_recarga) as valor_recarregado
from {{ ref('stg_recargas') }}
group by card_id, ano_mes, empresa_recarga
