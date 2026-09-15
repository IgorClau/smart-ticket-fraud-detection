"""
config.py — Parâmetros globais do gerador ViaCard v4.3.

Centraliza TODAS as distribuições obrigatórias e mapeamentos da spec, para que
qualquer ajuste de calibragem fique em um único lugar (e seja auditável).
Referências entre colchetes apontam para as seções do PROMPT MESTRE v4.3.
"""

# ---------------------------------------------------------------------------
# Operadoras (6) e seus arquivos-base [3]
# chave canônica -> (sufixo dos arquivos, nome exibido no extrato)
# ---------------------------------------------------------------------------
OPERADORAS = {
    "Ontur":       {"traj": "trajetos_e_tarifas_Ontur.xlsx",
                    "cod":  "codigos_linhas_ontur.xlsx",
                    "mat":  "Matricula_dos_carros_DETRAN_Ontur.xlsx",
                    "display": "ONTUR"},
    "Vanguarda":   {"traj": "trajetos_e_tarifas_Vanguarda.xlsx",
                    "cod":  "codigos_linhas_vanguarda.xlsx",
                    "mat":  "Matricula_dos_carros_DETRAN_Vanguarda.xlsx",
                    "display": "VANGUARDA"},
    "Pinheiros":   {"traj": "trajetos_e_tarifas_pinheiros.xlsx",
                    "cod":  "codigos_linhas_pinheiros.xlsx",
                    "mat":  "Matricula_dos_carros_DETRAN_Pinheiros.xlsx",
                    "display": "PINHEIROS"},
    "Rezendez":    {"traj": "trajetos_e_tarifas_rezendez.xlsx",
                    "cod":  "codigos_linhas_rezendez.xlsx",
                    "mat":  "Matricula_dos_carros_DETRAN_Rezendez.xlsx",
                    "display": "REZENDEZ"},
    "Tribuz":      {"traj": "trajetos_e_tarifas_tribuz.xlsx",
                    "cod":  "codigos_linhas_tribuz.xlsx",
                    "mat":  "Matricula_dos_carros_DETRAN_Tribuz.xlsx",
                    "display": "TRIBUZ"},
    "C das Ligas": {"traj": "trajetos_e_tarifas_C_das_Ligas.xlsx",
                    "cod":  "codigos_linhas_c_das_ligas.xlsx",
                    "mat":  "Matricula_dos_carros_DETRAN_C_das_Ligas.xlsx",
                    "display": "C DAS LIGAS"},
}

# ---------------------------------------------------------------------------
# Carteiras / cartão [3][16][34.3]
# ---------------------------------------------------------------------------
TETO_CARTEIRA = 1500.00        # teto por carteira
TETO_CARTAO   = 1500.00        # limite físico simultâneo (CART_A + CART_B)

# ---------------------------------------------------------------------------
# Distribuições obrigatórias [9][12][14][24][26]
# ---------------------------------------------------------------------------
DIST_MUDANCA_EMPRESA = {"nunca": 0.52, "uma": 0.28, "varias": 0.20}   # [9]
DIST_ESCALA          = {"6x1": 0.62, "5x2": 0.20, "especial": 0.18}    # [12]
DIST_FREQ_RECARGA    = {1: 0.60, 2: 0.20, 3: 0.20}                     # [14]
DIST_PERFIL_FRAUDE   = {"Regular": 0.73, "Suspeito": 0.03,             # [24]
                        "Fraudulento": 0.24}

# Referência calibrada em 2.500 extratos [26]
LOTE_REFERENCIA = {"Regular": 1825, "Suspeito": 75, "Fraudulento": 600}

ESCALAS_ESPECIAIS = ["12x36", "24x48"]

# Limite de fraude: nunca > 15% das utilizações do período [24]
FRACAO_MAX_FRAUDE = 0.15

# ---------------------------------------------------------------------------
# Perfil financeiro por SETOR da empresa -> data da recarga [23.1]
# Setores derivados de "Lista 150 empresas organizadas.txt".
#   industrial   -> dia útil fixo do mês
#   terceirizada -> datas variáveis
#   publica      -> último dia útil (é o padrão observado no modelo p/ Beneflex)
#   comercial    -> perto do fim do mês, com variação
# ---------------------------------------------------------------------------
SETOR_PERFIL_FINANCEIRO = {
    "COMÉRCIO DE VESTUÁRIO":       "comercial",
    "VAREJO GERAL":                "comercial",
    "ATACADO E DISTRIBUIÇÃO":      "terceirizada",
    "SUPERMERCADOS E MERCADOS":    "comercial",
    "SIDERURGIA E METALURGIA":     "industrial",
    "TRANSPORTE E LOGÍSTICA":      "terceirizada",
    "CONSTRUÇÃO CIVIL":            "industrial",
    "TICKETEIRAS E BENEFÍCIOS":    "publica",
}
DIA_UTIL_FIXO_INDUSTRIAL = 5   # 5º dia útil do mês (perfil industrial)

# ---------------------------------------------------------------------------
# Status de embarque (Tipo Emb.) [3][modelo]. Só NORMAL debita.
# ---------------------------------------------------------------------------
STATUS_NORMAL = "NORMAL"
STATUS_ERRO   = ["ERRO DE LEITURA", "ERRO DE GRAVAÇÃO"]
STATUS_SEM_SALDO = "SALDO INSUFICIENTE"
# probabilidade de um embarque legítimo virar erro de validador (sem débito)
PROB_ERRO_VALIDADOR = 0.010

# ---------------------------------------------------------------------------
# Estados do cartão [34.1]
# ---------------------------------------------------------------------------
ESTADOS_CARTAO = ["Ativo", "Bloqueado", "Cancelado", "Segunda via",
                  "Expirado", "Em análise"]

# ---------------------------------------------------------------------------
# Catálogo de fraudes [25]
# ---------------------------------------------------------------------------
CATALOGO_FRAUDES = [
    "Venda de créditos", "Empréstimo do cartão", "Endereço falso",
    "Uso em férias", "Uso em licença", "Desvio de finalidade",
    "Clonagem", "Replay", "Recarga clandestina", "Uso offline",
    "Conluio operacional", "Uso de gratuidade associado ao VT",
]

# ---------------------------------------------------------------------------
# Janela temporal [2]
# ---------------------------------------------------------------------------
DATA_FIM_PADRAO   = (2025, 12, 31)   # extrato termina aqui (mais recente no topo)
ANOS_HISTORICO    = 5

# ---------------------------------------------------------------------------
# Hábitos de horário [21][23][26]  (segundos uniformes; nunca redondos)
# ---------------------------------------------------------------------------
# média (min do dia) e desvio p/ ida e volta — distribuição Normal [26]
HORA_IDA_MEDIA_MIN   = 7 * 60       # ~07:00
HORA_IDA_STD_MIN     = 22
HORA_VOLTA_MEDIA_MIN = 17 * 60 + 30  # ~17:30
HORA_VOLTA_STD_MIN   = 20

# vacância entre 6 e 14 meses [22]
VACANCIA_MIN_MESES = 6
VACANCIA_MAX_MESES = 14

# bloqueio de recarga por mais de 18 meses [18]
BLOQUEIO_MESES = 18

# ---------------------------------------------------------------------------
# Sazonalidade — multiplicador de intensidade de viagens por mês [23.2]
# ---------------------------------------------------------------------------
SAZONALIDADE_MES = {
    1: 0.80,   # Janeiro: menos viagens
    2: 0.92,   # Carnaval tratado à parte (dias sem uso)
    3: 1.00, 4: 1.00, 5: 1.00, 6: 1.00,
    7: 0.78,   # Julho: férias
    8: 1.00, 9: 1.00, 10: 1.00, 11: 1.00,
    12: 0.85,  # Dezembro: redução parcial
}

# Corte de realismo [33]
CORTE_REALISMO = 95.0

# ---------------------------------------------------------------------------
# v4.4 — fraudes materializadas e hábitos legítimos
# ---------------------------------------------------------------------------
# fração das utilizações do período convertida em eventos de fraude (<= 15%) [24]
INTENSIDADE_FRAUDE = {"Fraudulento": (0.05, 0.12), "Suspeito": (0.01, 0.035)}

# Hábitos legítimos que se parecem com fraude. Sem eles, qualquer embarque fora
# da rotina denunciaria o fraudador e a detecção ficaria artificialmente trivial.
PROB_TEM_LAZER = 0.45            # passageiros que usam o cartão em folgas
LAZER_PROB_FOLGA = (0.04, 0.15)  # chance, por dia de folga, de um passeio (ida/volta)
PROB_VIAGEM_INTERMUN = 0.20      # passageiros com viagens intermunicipais eventuais
VIAGENS_INTERMUN_ANO = (1, 4)
