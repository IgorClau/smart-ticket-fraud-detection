select operador_display, codigo_linha, trajeto, tipo_linha, tarifa_tabela
from {{ source('silver', 'dim_linha') }}
