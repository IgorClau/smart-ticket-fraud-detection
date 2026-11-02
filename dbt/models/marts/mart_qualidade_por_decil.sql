-- Pergunta q10: o score concentra fraude nos decis mais altos? (avaliação — usa o rótulo)
with d as (
    select is_fraude, ntile(10) over (order by anomaly_score desc) as decil
    from {{ ref('stg_scores') }}
)
select decil, count(*) as cartoes, sum(is_fraude) as fraudes,
       round(avg(is_fraude), 3) as taxa_fraude
from d
group by decil
