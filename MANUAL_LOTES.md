# Manual — processar os lotes 1 a 9

Como transformar as pastas `lote1` … `lote9` de `04 - Case Data Eng Projeto\04.2 - Dados Brutos - Lotes`
(13.817 extratos, 2,2 GB) em tabelas prontas para modelo e Power BI.

Tudo é executado da raiz do repositório: `04 - Case Data Eng Projeto\04.1 - Repositório\smart-ticket-fraud-detection`.
Os lotes ficam dois níveis acima, em `../../04.2 - Dados Brutos - Lotes/` — os comandos abaixo usam esse caminho relativo.

---

## 1. O que são esses lotes

| Lote | Extratos | Tamanho | Rótulo de fraude |
|---|---:|---:|---|
| lote1 | 500 | 80 MB | não |
| lote2 | 1.016 | 165 MB | não |
| lote3 | 1.016 | 165 MB | não |
| lote4 | 1.905 | 308 MB | não |
| lote5 | 2.270 | 365 MB | não |
| lote6 | 2.271 | 366 MB | não |
| lote7 | 2.269 | 366 MB | não |
| lote8 | 500 | 83 MB | sim (`rotulos.csv`) |
| lote9 | 2.070 | 339 MB | sim (`rotulos.csv`) |
| **Total** | **13.817** | **2,2 GB** | 2 lotes com rótulo |

São **gerações independentes** do gerador ViaCard, feitas em momentos diferentes. Três consequências
que o pipeline já trata — e que explicam por que não basta jogar tudo numa pasta só:

1. **O mesmo número de cartão se repete entre lotes**, com nome e histórico diferentes. Numa amostra de
   221 cartões apareceram 4 repetições. Juntar por `card_id` fundiria pessoas distintas. A silver resolve
   com a chave `lote:cartão` (`aplicar_chave_lote`), guardando o número original em `card_id_origem`.
2. **Os lotes antigos gravam a operadora sem espaços** (`CDASLIGAS` em vez de `C DAS LIGAS`). Sem
   padronizar, 14% dos embarques ficavam sem tipo de linha, sem tarifa de tabela e reprovados na checagem
   de frota — e o Power BI mostraria duas operadoras onde há uma. A silver canoniza pelo nome da base
   de referência (`canonizar_operadora`).
3. **Fraude sem rastro nos lotes 8 e 9.** Eles têm `rotulos.csv`, mas foram gerados quando a fraude era
   apenas uma marca interna: o extrato do fraudador é igual ao do usuário regular. Servem para treinar e
   pontuar, **não** para medir o modelo (veja a seção 6).
4. **Parte dos extratos viola as regras do próprio sistema.** No lote1, 31 dos 500 cartões têm embarque
   `NORMAL` com tarifa zero e sem `D/C`, ou saldo acima do teto de R$ 1.500 (chegando a R$ 2.416). Como
   não dá para calcular saldo médio ou razão recarga/consumo a partir de um histórico assim, esses
   cartões vão para **quarentena** (`silver/quarentena_cartoes.parquet`), com o motivo registrado, e o
   restante do lote segue normalmente. O status também aparece sem acento (`ERRO DE GRAVACAO`), o que a
   silver canoniza.

---

## 2. Antes de começar

| Requisito | Valor |
|---|---|
| Python | 3.14 com `pip install -r requirements.txt` |
| Espaço em disco | ~2,5 GB livres em `data/processed/lotes` |
| Memória | 16 GB é suficiente: processa-se **um lote por vez** |
| Tempo | ~45 a 60 min para os nove lotes |

Feche os `.xlsx` no Excel antes de rodar: o Windows trava o arquivo aberto e a leitura falha.

---

## 3. Conferir o inventário

```bash
python -c "import glob,os; [print(f'{os.path.basename(d):8} {len(glob.glob(d+chr(47)+chr(42)+\".xlsx\")):>6} extratos') for d in sorted(glob.glob(r'../../04.2 - Dados Brutos - Lotes/lote*'))]"
```

---

## 4. Processar tudo

```bash
python -m src.data_pipeline.lotes --raw-dirs "../../04.2 - Dados Brutos - Lotes/lote*" --out data/processed/lotes --workers 7 --continuar
```

O que acontece, lote a lote: **bronze** (lê os `.xlsx` em 7 processos), **silver** (tipagem, ordem
cronológica, continuidade do saldo, dimensões e 19–20 checagens de qualidade) e **gold** (features por
cartão e fatos do BI). No fim, a consolidação junta o que é pequeno.

Opções úteis:

| Flag | Para quê |
|---|---|
| `--continuar` | pula lotes já processados — use sempre que retomar |
| `--so-consolidar` | não reprocessa nada, só refaz a consolidação |
| `--workers N` | menos processos se a máquina ficar lenta (padrão 7) |
| `--raw-dirs ".../lote3"` | processa um lote específico |

Saída:

```
data/processed/lotes/
├── lote1/ … lote9/          bronze, silver e gold de cada lote (partições)
└── consolidado/
    ├── gold/card_features.parquet          1 linha por cartão (13,8 mil)
    ├── gold/fato_embarques_mensal.parquet  fato leve — o padrão do Power BI
    ├── gold/fato_embarques_diario/         uma partição .parquet por lote
    ├── gold/fato_recargas_mensal/
    ├── gold/dim_linha.parquet
    ├── silver/cards.parquet, labels_cartao.parquet, dim_*.parquet
    ├── qualidade_por_lote.json
    └── resumo_lotes.csv
```

Em cada `loteN/silver/` ficam ainda `transactions.parquet` (a tabela detalhada daquele lote),
`quality_report.json` e, quando houver, `quarentena_cartoes.parquet`.

### Resultado observado (execução completa, 7 workers)

| Lote | Arquivos | Transações | Cartões na gold | Quarentena | Qualidade | Tempo |
|---|---:|---:|---:|---:|---|---:|
| lote1 | 500 | 1.556.799 | 469 | 31 | 19/20 | 2,1 min |
| lote2 | 1.016 | 3.236.405 | 957 | 58 | 19/20 | 4,0 min |
| lote3 | 1.016 | 3.229.625 | 948 | 67 | 19/20 | 4,3 min |
| lote4 | 1.905 | 6.037.927 | 1.749 | 105 | 19/20 | 7,5 min |
| lote5 | 2.270 | 7.139.173 | 2.121 | 126 | 19/20 | 8,8 min |
| lote6 | 2.271 | 7.158.389 | 2.119 | 121 | 19/20 | 8,6 min |
| lote7 | 2.269 | 7.162.599 | 2.122 | 122 | 19/20 | 8,5 min |
| lote8 | 500 | 1.518.965 | 500 | 0 | 21/21 | 1,8 min |
| lote9 | 2.070 | 6.151.318 | 2.043 | 0 | 21/21 | 7,2 min |
| **Total** | **13.817** | **43.191.200** | **13.028** | **630 (4,6%)** | 9/9 lotes ok | **52,7 min** |

Motivos da quarentena: 400 cartões com embarque sem tarifa e `D/C` incoerente, 225 com saldo acima do
teto e 5 com os dois problemas. Nenhum arquivo falhou na leitura.

A diferença entre arquivos e cartões vem de duas fontes, ambas tratadas sozinhas: **cópias do Windows**
(`extrato_...(1).xlsx`, conteúdo idêntico) que a deduplicação da silver elimina, e os cartões em quarentena.

---

## 5. Conferir a qualidade

```bash
python -c "import pandas as pd; print(pd.read_csv(r'data/processed/lotes/consolidado/resumo_lotes.csv').to_string(index=False))"
```

```bash
python -c "import json; [print(c['lote'], c['aprovadas'], '/', c['total'], 'falhas:', c['falhas']) for c in json.load(open(r'data/processed/lotes/consolidado/qualidade_por_lote.json', encoding='utf-8'))]"
```

Esperado nos lotes 1 a 7: **19/20**, com o único alerta `rotulos_presentes` (esses lotes não têm rótulo).
Nos lotes 8 e 9, 20/20.

Veja quantos cartões foram para quarentena e por quê:

```bash
python -c "import glob,pandas as pd; q=pd.concat([pd.read_parquet(f) for f in glob.glob(r'data/processed/lotes/lote*/silver/quarentena_cartoes.parquet')]); print(len(q),'cartões'); print(q.motivos.value_counts().to_string())"
```

Regras do pipeline:

- checagem de severidade **`erro`** interrompe o lote — dado quebrado não chega à gold;
- **quarentena acima de 10% dos cartões** de um lote também interrompe: sinal de que a origem mudou de
  formato, e não de um punhado de extratos defeituosos;
- cartões em quarentena somem de `cards`, `labels_cartao` e das features — reveja o arquivo antes de
  descartá-los, porque um extrato inconsistente também pode ser sintoma de fraude no sistema real.

---

## 6. Pontuar os 13,8 mil cartões

O modelo de produção é **não supervisionado**, então treina com todos os cartões, com ou sem rótulo.
Use pastas de artefato separadas para **não sobrescrever** o modelo do lote v4.4:

```bash
python -m src.training.train --gold-dir data/processed/lotes/consolidado/gold --silver-dir data/processed/lotes/consolidado/silver --artifacts-dir mlops/artifacts_lotes --reports-dir mlops/reports_lotes
```

Isso grava `consolidado/gold/card_scores.parquet` (score, percentil, alerta, cluster e motivo por cartão),
além de `metrics.md`, `alertas_explicados.csv` e figuras em `mlops/reports_lotes`.

Resultado observado: 13.028 cartões pontuados, **1.303 alertas** (top 10%), em 65 s.

> **Leia as métricas com cuidado.** A avaliação usa só os 2.519 cartões rotulados (lotes 8 e 9), e esses
> rótulos não têm contrapartida observável no extrato. O resultado medido foi:
>
> | Modelo | ROC-AUC | PR-AUC |
> |---|---|---|
> | Isolation Forest | 0,503 | 0,252 |
> | LOF | 0,453 | 0,225 |
> | Gradient Boosting supervisionado (teto) | 0,536 | 0,291 |
>
> Ou seja: **acaso**. Como até o modelo supervisionado, que enxerga os rótulos, fica em 0,536, a conclusão
> é que o sinal não existe nos dados — não é limitação do modelo. Compare com o lote novo
> (`data/raw/viacard_v44`), gerado com fraude materializada, onde o mesmo pipeline dá **ROC-AUC 0,916**.
>
> Os scores dos lotes antigos continuam úteis como **ranking de anomalia comportamental** para priorizar
> auditoria; o que não dá é chamar de "detecção de fraude validada".

---

## 7. Levar para o Power BI (comparação)

O relatório *Fila de Auditoria* lê `data/processed/powerbi`, que é a exportação do `viacard_v44`. Para
comparar com os lotes sem sobrescrevê-la, exporte para outra pasta e aponte as consultas do Power BI para ela:

```bash
python -m src.data_pipeline.export_bi --gold data/processed/lotes/consolidado/gold --out data/processed/powerbi_lotes
```

Saída medida (20 s, 38 MB no total):

| Arquivo | Linhas | Tamanho |
|---|---:|---:|
| `card_scores.parquet` | 13.028 | 0,6 MB |
| `card_features.parquet` | 13.028 | 1,6 MB |
| `fato_embarques_mensal.parquet` | 807.982 | 4,0 MB |
| `fato_embarques_diario.parquet` | 16.010.833 | 29,5 MB |
| `fato_recargas_mensal.parquet` | 740.966 | 3,4 MB |
| `dim_linha.parquet` | 226 | 0,0 MB |

Se o dashboard não precisar do histórico inteiro, corte o período com `--desde 2023-01-01` (o fato
diário é o único realmente grande). Para CSV, acrescente `--formato csv`.

O passo a passo no Power BI Desktop — conexão, relacionamentos, medidas e páginas — está em
[`mlops/powerbi/README.md`](mlops/powerbi/README.md).

---

## 8. Opcional: consultar em SQL

```bash
docker compose up -d postgres
```

```bash
set PG_DSN=postgresql://stf:stf_local@localhost:5432/bilhetagem
```

O carregador leva uma silver por vez (a tabela `transacao` é a detalhada, não a consolidada).
Comece por um lote — 1,5 milhão de linhas entra em ~2 min:

```bash
python -m src.data_pipeline.sql.load_postgres --silver data/processed/lotes/lote1/silver --gold data/processed/lotes/lote1/gold --respostas src/data_pipeline/sql/03_respostas_lote1.md
```

As 11 perguntas de negócio rodam ao fim da carga e as respostas vão para o arquivo indicado.
Carregar os 9 lotes (~37 milhões de linhas) leva cerca de 50 min e ~12 GB no volume do Postgres;
para análise exploratória, prefira um lote ou a camada gold consolidada.

---

## 9. Volume maior: o mesmo pipeline em Spark

Acima de ~50 milhões de linhas, troque o pandas pelo Spark com Delta (o mesmo código roda nos dois):

```bash
docker compose --profile spark run --rm -e RAW_PATH=/workspace/data/raw/viacard_v44 spark
```

Na nuvem é esse caminho que o Azure Data Factory orquestra, com os notebooks em
`src/data_pipeline/spark/` rodando no Databricks.

---

## 10. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `PermissionError` num `.xlsx` | arquivo aberto no Excel; feche e rode de novo com `--continuar` |
| Memória estourando | reduza `--workers`; nunca processe vários lotes no mesmo passo de silver |
| `nenhuma pasta encontrada` | use barras normais no caminho: `"C:/Users/.../lote*"` |
| Parou no meio | `--continuar` retoma do lote seguinte; um lote incompleto é refeito inteiro |
| `card_id repetido entre lotes` na consolidação | sinal de que a chave por lote não foi aplicada: reprocesse o lote (bronze precisa ter a coluna `lote`) |
| Quero refazer só a consolidação | `--so-consolidar` |
