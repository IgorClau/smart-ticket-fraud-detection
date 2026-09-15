-- Perguntas de negócio sobre a bilhetagem — Fundamentos de SQL (PostgreSQL).
-- Cada bloco começa com "-- name: <id> | <pergunta>"; load_postgres.py --run executa todos
-- e grava as respostas em 03_respostas.md.
SET search_path TO bilhetagem;

-- name: q01 | Quanto cada operadora transportou e faturou por ano?
SELECT operador_display,
       date_part('year', event_ts)::int                 AS ano,
       count(*) FILTER (WHERE is_debito)                AS embarques_pagos,
       round(sum(vd) FILTER (WHERE is_debito), 2)       AS receita
FROM transacao
WHERE tipo = 'USADO'
GROUP BY operador_display, ano
ORDER BY ano, receita DESC;

-- name: q02 | Quais as 10 linhas mais usadas em 2025 e quanto representam do total?
WITH por_linha AS (
    SELECT t.operador_display, t.codigo_linha, l.trajeto, count(*) AS embarques
    FROM transacao t
    JOIN linha l USING (operador_display, codigo_linha)
    WHERE t.is_debito AND t.event_ts >= '2025-01-01'
    GROUP BY t.operador_display, t.codigo_linha, l.trajeto
)
SELECT operador_display, codigo_linha, trajeto, embarques,
       round(100.0 * embarques / sum(embarques) OVER (), 2) AS pct_total,
       rank() OVER (ORDER BY embarques DESC)                AS posicao
FROM por_linha
ORDER BY embarques DESC
LIMIT 10;

-- name: q03 | Qual o horário de pico em dias úteis x fim de semana?
SELECT extract(hour FROM event_ts)::int AS hora,
       count(*) FILTER (WHERE extract(isodow FROM event_ts) < 6)  AS dias_uteis,
       count(*) FILTER (WHERE extract(isodow FROM event_ts) >= 6) AS fim_de_semana
FROM transacao
WHERE is_debito
GROUP BY hora
ORDER BY hora;

-- name: q04 | Como variou o volume mês a mês em 2025 (MoM)?
WITH mensal AS (
    SELECT date_trunc('month', event_ts)::date AS mes, count(*) AS embarques
    FROM transacao
    WHERE is_debito AND event_ts >= '2024-12-01'
    GROUP BY mes
)
SELECT mes, embarques,
       lag(embarques) OVER (ORDER BY mes)                                                   AS mes_anterior,
       round(100.0 * (embarques - lag(embarques) OVER (ORDER BY mes))
             / nullif(lag(embarques) OVER (ORDER BY mes), 0), 1)                             AS variacao_pct,
       round(avg(embarques) OVER (ORDER BY mes ROWS BETWEEN 2 PRECEDING AND CURRENT ROW))   AS media_movel_3m
FROM mensal
ORDER BY mes;

-- name: q05 | Quem são os 3 maiores usuários de cada operadora?
WITH uso AS (
    SELECT operador_display, card_id, count(*) AS embarques
    FROM transacao
    WHERE is_debito
    GROUP BY operador_display, card_id
), ranqueado AS (
    SELECT *, dense_rank() OVER (PARTITION BY operador_display ORDER BY embarques DESC) AS posicao
    FROM uso
)
SELECT r.operador_display, r.posicao, c.nome, r.embarques
FROM ranqueado r
JOIN cartao c USING (card_id)
WHERE r.posicao <= 3
ORDER BY r.operador_display, r.posicao;

-- name: q06 | Quais cartões repetem a MESMA transação em menos de 5 minutos (indício de replay)?
WITH seq AS (
    SELECT card_id, event_ts, descricao,
           lag(event_ts)  OVER w AS ts_anterior,
           lag(descricao) OVER w AS desc_anterior
    FROM transacao
    WHERE tipo = 'USADO'
    WINDOW w AS (PARTITION BY card_id ORDER BY seq)
)
SELECT c.nome, s.card_id, count(*) AS repeticoes,
       min(s.event_ts - s.ts_anterior) AS menor_intervalo
FROM seq s
JOIN cartao c USING (card_id)
WHERE s.descricao = s.desc_anterior
  AND s.event_ts - s.ts_anterior < interval '5 minutes'
GROUP BY c.nome, s.card_id
ORDER BY repeticoes DESC
LIMIT 10;

-- name: q07 | Qual a maior sequência de dias seguidos com uso de cada cartão? (gaps and islands)
WITH dias AS (
    SELECT DISTINCT card_id, event_ts::date AS dia
    FROM transacao
    WHERE tipo = 'USADO'
), ilhas AS (
    SELECT card_id, dia,
           dia - (row_number() OVER (PARTITION BY card_id ORDER BY dia))::int AS grupo
    FROM dias
), sequencias AS (
    SELECT card_id, grupo, count(*) AS dias_seguidos, min(dia) AS inicio, max(dia) AS fim
    FROM ilhas
    GROUP BY card_id, grupo
)
SELECT DISTINCT ON (s.card_id) c.nome, s.dias_seguidos, s.inicio, s.fim
FROM sequencias s
JOIN cartao c USING (card_id)
ORDER BY s.card_id, s.dias_seguidos DESC
LIMIT 15;

-- name: q08 | Existem embarques NORMAL que não debitaram o saldo (validador offline)?
WITH saldo AS (
    SELECT card_id, seq, event_ts, descricao, vd, saldo, is_debito,
           lag(saldo) OVER (PARTITION BY card_id ORDER BY seq) AS saldo_anterior
    FROM transacao
)
SELECT c.nome, s.card_id, count(*) AS embarques_sem_debito, round(sum(s.vd), 2) AS valor_nao_debitado
FROM saldo s
JOIN cartao c USING (card_id)
WHERE s.is_debito AND s.saldo = s.saldo_anterior
GROUP BY c.nome, s.card_id
ORDER BY embarques_sem_debito DESC
LIMIT 10;

-- name: q09 | Quais recargas entraram fora da dupla passada e com valor redondo?
WITH prox AS (
    SELECT card_id, event_ts, tipo, empresa_recarga, vd,
           lead(event_ts) OVER (PARTITION BY card_id ORDER BY seq) AS ts_seguinte,
           lead(tipo)     OVER (PARTITION BY card_id ORDER BY seq) AS tipo_seguinte
    FROM transacao
)
SELECT c.nome, p.empresa_recarga, count(*) AS recargas_suspeitas, round(sum(p.vd), 2) AS valor
FROM prox p
JOIN cartao c USING (card_id)
WHERE p.tipo = 'REC'
  AND NOT (p.ts_seguinte = p.event_ts AND p.tipo_seguinte = 'USADO')
  AND p.vd % 10 = 0
GROUP BY c.nome, p.empresa_recarga
ORDER BY recargas_suspeitas DESC
LIMIT 10;

-- name: q10 | O score do modelo concentra fraude nos decis mais altos?
WITH decis AS (
    SELECT s.card_id, s.anomaly_score, r.is_fraude,
           ntile(10) OVER (ORDER BY s.anomaly_score DESC) AS decil
    FROM score_cartao s
    JOIN rotulo_cartao r USING (card_id)
)
SELECT decil, count(*) AS cartoes, sum(is_fraude) AS fraudes,
       round(100.0 * avg(is_fraude), 1) AS taxa_fraude_pct,
       round(100.0 * sum(sum(is_fraude)) OVER (ORDER BY decil) / sum(sum(is_fraude)) OVER (), 1) AS recall_acumulado_pct
FROM decis
GROUP BY decil
ORDER BY decil;

-- name: q11 | Em que perfil de cartão (cluster) a fraude se esconde?
SELECT s.cluster, count(*) AS cartoes,
       round(100.0 * avg(r.is_fraude), 1) AS taxa_fraude_pct,
       round(avg(s.anomaly_score)::numeric, 4) AS score_medio,
       sum(s.alerta) AS em_alerta
FROM score_cartao s
JOIN rotulo_cartao r USING (card_id)
GROUP BY s.cluster
ORDER BY taxa_fraude_pct DESC;
