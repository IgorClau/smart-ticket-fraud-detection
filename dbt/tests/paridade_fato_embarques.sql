-- Paridade dbt x pipeline Python: o fato em SQL precisa bater com gold/fato_embarques_diario.
-- Retorna linhas só se os totais divergirem (o teste falha).
with d as (
    select count(*) as linhas, sum(n_embarques) as emb, round(sum(valor_debitado), 2) as receita
    from {{ ref('fct_embarques_diario') }}
), p as (
    select count(*) as linhas, sum(n_embarques) as emb, round(sum(valor_debitado), 2) as receita
    from {{ source('gold', 'fato_embarques_diario') }}
)
select * from d cross join p
where d.linhas <> p.linhas or d.emb <> p.emb or abs(d.receita - p.receita) > 0.01
