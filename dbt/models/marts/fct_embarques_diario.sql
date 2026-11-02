-- Grão: cartão x dia x linha. Reproduz gold/fato_embarques_diario em SQL (paridade testada).
select
    card_id, data, operador_display, codigo_linha, tipo_linha,
    count(*)                                       as n_embarques,
    sum(case when is_debito then 1 else 0 end)     as n_debitos,
    sum(valor_debitado)                            as valor_debitado,
    sum(case when is_erro then 1 else 0 end)       as n_erros,
    sum(case when is_noite then 1 else 0 end)      as n_noite
from {{ ref('stg_embarques') }}
group by card_id, data, operador_display, codigo_linha, tipo_linha
