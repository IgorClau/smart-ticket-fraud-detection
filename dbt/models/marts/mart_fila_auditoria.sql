-- Fila de auditoria: top 10% dos scores (alerta = 1), com nome e motivo SHAP.
-- É a tabela que o time de auditoria consome (Power BI / API).
select s.posicao_fila, c.nome, s.card_id, round(s.anomaly_score, 4) as anomaly_score,
       s.cluster, s.motivo_principal, s.principais_motivos
from {{ ref('stg_scores') }} s
join {{ ref('stg_cartoes') }} c on c.card_id = s.card_id
where s.alerta = 1
