-- Esquema relacional (PostgreSQL) para os Fundamentos de SQL.
-- Carregado a partir da silver/gold por: python -m src.data_pipeline.sql.load_postgres

CREATE SCHEMA IF NOT EXISTS bilhetagem;
SET search_path TO bilhetagem;

CREATE TABLE IF NOT EXISTS cartao (
    card_id  text PRIMARY KEY,
    nome     text NOT NULL,
    arquivo  text
);

CREATE TABLE IF NOT EXISTS linha (
    operador_display text,
    codigo_linha     text,
    trajeto          text,
    tipo_linha       text CHECK (tipo_linha IN ('MUNICIPAL', 'INTERMUNICIPAL')),
    tarifa_tabela    numeric(8, 2),
    PRIMARY KEY (operador_display, codigo_linha)
);

CREATE TABLE IF NOT EXISTS transacao (
    card_id              text REFERENCES cartao (card_id),
    seq                  integer,
    event_ts             timestamp NOT NULL,
    tipo                 text CHECK (tipo IN ('USADO', 'REC')),
    status_emb           text,
    descricao            text,
    operador_display     text,
    veiculo              integer,
    codigo_linha         text,
    sentido              char(1),
    empresa_recarga      text,
    cart_a               numeric(8, 2),
    cart_b               numeric(8, 2),
    saldo                numeric(8, 2),
    vd                   numeric(8, 2),
    is_debito            boolean,
    inconsistencia_saldo boolean,
    PRIMARY KEY (card_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_transacao_ts ON transacao (event_ts);
CREATE INDEX IF NOT EXISTS ix_transacao_linha ON transacao (operador_display, codigo_linha);

CREATE TABLE IF NOT EXISTS rotulo_cartao (
    card_id      text PRIMARY KEY REFERENCES cartao (card_id),
    classe       text,
    is_fraude    smallint,
    tipos_fraude text
);

CREATE TABLE IF NOT EXISTS score_cartao (
    card_id          text PRIMARY KEY REFERENCES cartao (card_id),
    anomaly_score    double precision,
    percentil        double precision,
    alerta           smallint,
    rank             integer,
    cluster          integer,
    motivo_principal text
);
