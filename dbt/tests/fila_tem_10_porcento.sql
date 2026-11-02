-- Regra de negócio: a fila de auditoria tem 10% dos cartões (audit_fraction = 0.10).
with t as (select count(*) as n from {{ ref('stg_scores') }}),
     f as (select count(*) as n from {{ ref('mart_fila_auditoria') }})
select * from t cross join f where f.n <> cast(round(t.n * 0.10) as int)
