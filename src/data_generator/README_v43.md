# Gerador de Extratos Sintéticos ViaCard — v4.3

Gera extratos de utilização de bilhetagem eletrônica (cartão **ViaCard**, modelo
dupla carteira) **sintéticos, realistas e auditáveis**, no layout idêntico ao
extrato-modelo, para treino e avaliação de modelos de **detecção de fraude**.

Cada extrato cobre ~5 anos de histórico de um passageiro do corredor Sul
Fluminense (RJ), com perfil, empregadora(s), linha/tarifa, recargas e saldo
totalmente consistentes — e passa por um **auditor independente** (V1–V15) antes
de ser exportado.

---

## 1. Arquitetura (modular, espelhando os Módulos 0–9 da spec)

```
viacard/
├── config.py      # Módulo — parâmetros e TODAS as distribuições obrigatórias
├── bases.py       # Módulo 0 — carregamento robusto das 19 bases (join trajeto↔código)
├── motor.py       # Módulos 1–7 — perfil, empresa, trajeto, cronologia,
│                  #               recargas, SALDO (dupla carteira+FIFO), fraudes
├── validacao.py   # Módulo 8 — auditor independente V1–V15 + realismo (5 dimensões)
├── export.py      # Módulo 9 — escrita XLSX no layout exato do modelo
└── gerador.py     # Orquestração — reseed até validar, lote, manifesto, rótulos
run.py             # CLI
```

O motor é **determinístico por `seed`** (reprodutível), e o auditor é
**separado** do gerador: ele reprocessa os eventos já materializados e confere as
invariantes, sem "confiar" em como foram produzidos.

---

## 2. Uso rápido

Requisitos: Python 3.10+, `openpyxl`. (Para `--recalc`: LibreOffice — usa o
`recalc.py` da skill de xlsx.)

```bash
# 10 extratos, seed inicial 1000, com recálculo das fórmulas (grava valores)
python run.py --n 10 --seed 1000 --out ./saida --recalc

# apontando para outra pasta de bases
python run.py --n 20 --seed 0 --out ./saida --bases /caminho/para/bases
```

Saída em `--out`:
- `extrato_de_utilizacao_<nome>.xlsx` — um por passageiro;
- `manifesto.csv` — uma linha por extrato (seed, classe, escala, nº de eventos,
  recargas, realismo, se passou nas validações…);
- `rotulos.csv` — rótulo por extrato para treino supervisionado
  (`is_fraude` + tipos de fraude).

---

## 3. Gerando 2.500 extratos (em lotes)

Um chat não produz 2.500 arquivos, mas o gerador foi feito para escalar. Rode em
blocos, variando o seed inicial para não repetir passageiros:

```bash
python run.py --n 500 --seed 0     --out ./lote_01
python run.py --n 500 --seed 500   --out ./lote_02
python run.py --n 500 --seed 1000  --out ./lote_03
python run.py --n 500 --seed 1500  --out ./lote_04
python run.py --n 500 --seed 2000  --out ./lote_05
```

Depois basta concatenar os cinco `manifesto.csv`/`rotulos.csv`. Sem `--recalc` a
geração fica em ~0,3 s/extrato; o Excel/LibreOffice recalcula o `SALDO` ao abrir.
Use `--recalc` quando precisar que ferramentas que leem valores em cache
(`pandas`, `load_workbook(data_only=True)`) já enxerguem o `SALDO` calculado.

A proporção de classes emerge da distribuição obrigatória (~73% Regular, ~3%
Suspeito, ~24% Fraudulento [24]); em lotes grandes ela converge para o alvo.

---

## 4. Como o SALDO funciona (dupla carteira)

Mecânica observada no extrato-modelo e reproduzida fielmente:

- duas carteiras **CART A** e **CART B**; a soma nunca passa de **R$ 1.500**;
- as recargas compradas pela empregadora entram numa **fila FIFO**;
- uma recarga só **entra** quando a carteira de trabalho não cobre mais uma
  tarifa **e** a soma final ≤ R$ 1.500 — na **dupla passada**, a linha **REC**
  aparece **antes** do embarque no mesmo instante;
- só embarques **NORMAL** debitam; **ERRO DE LEITURA/GRAVAÇÃO** e **SALDO
  INSUFICIENTE** não mexem no saldo (mas registram a tarifa em VD);
- uma recarga bloqueada por **> 18 meses** trava as posteriores (regra [18]);
- **recarga até um alvo**: a cada mês o RH completa o crédito disponível até
  ~2,2 meses de necessidade — evita tanto acúmulo irreal de recargas quanto
  falta de saldo, mantendo os "Lançamentos Administrativos" num patamar realista.

O `SALDO` é gravado como **fórmula** `=CART_A+CART_B` (não hard-coded), como no
modelo.

---

## 5. Validações V1–V15 (auditor)

`validacao.validar()` confere, entre outras: saldo nunca negativo (V1),
cronologia em ordem (V2), tempo mínimo entre embarques (V3/V14), tarifa dentro da
base (V4), veículo compatível e existente na frota (V5), empresa da recarga =
empregadora da **data da compra** (V6), horários orgânicos sem redondos (V7),
entrada de recarga sem estourar o teto (V10), no máximo uma recarga por instante
(V11) e dupla passada REC-antes-do-USADO (V12). As demais (V8, V9, V13, V15) são
garantidas por construção. `pontuar_realismo()` devolve nota por dimensão
(Temporal, Financeiro, Geográfico, Operacional, Comportamental) e a **Geral**;
o orquestrador re-semeia se algo falhar ou a nota ficar abaixo de 95.

---

## 6. Decisões de modelagem (documentadas)

- **Empregadora ∈ 150 empresas**; o rótulo da recarga usa o nome dela
  ("Recarga <empresa> - Pedido <n>"), como no modelo.
- **Perfil financeiro por setor** define a data da recarga [23.1]: industrial →
  5º dia útil; pública/ticketeira → último dia útil; terceirizada → data
  variável; comercial → fim de mês com variação.
- **Recarga carrega o nome de quem comprou**: pode ser sacada após uma troca de
  empresa, então V6 casa pela data da **compra**, não da entrada.
- **Frequência de recarga** [14] = nº de compras no mês; o valor total do mês é
  dividido entre elas (sem gerar excesso).

---

## 7. Limitações conhecidas / próximos passos

- As fraudes são marcadas analiticamente sobre embarques normais (rótulo por
  extrato). Uma evolução natural é materializar **rótulos por evento**
  (linha-a-linha) e assinaturas geográficas/temporais específicas por tipo de
  fraude, úteis para o split entidade-a-entidade e para o Isolation Forest.
- O corredor é tratado como linha única por época (consistência geográfica
  trivial); dá para estender para baldeações intermunicipais reais usando as
  bases já carregadas.
```
