-- Saída do modelo de ML. O rótulo (is_fraude / classe) só é usado em avaliação, nunca em feature.
select card_id, anomaly_score, percentil, alerta, `rank` as posicao_fila, cluster,
       motivo_principal, principais_motivos, classe, is_fraude, tipos_fraude
from {{ source('gold', 'card_scores') }}
