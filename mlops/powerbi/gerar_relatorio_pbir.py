"""Gera o relatório "Fila de Auditoria" em formato PBIR (pasta .Report do PBIP)."""
import json, os, shutil, sys, itertools

REPORT_DIR = sys.argv[1]          # ...\Fila de Auditoria.Report
THEME_SRC = sys.argv[2]           # Fluent2-CY26SU08.json extraído do pbix (tema base)
CUSTOM_SRC = (sys.argv[3] if len(sys.argv) > 3 else
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "tema_smart_ticket_escuro.json"))
THEME = "Fluent2-CY26SU08"
CUSTOM = "SmartTicketEscuro.json"   # tema escuro-pastel por cima do base (RegisteredResources)
TXT, TXT2 = "#E6E9EF", "#B7BDCA"     # texto principal e secundário do tema
SUBTITULO = "Smart Ticket Fraud Detection · viacard_v44 · 2.500 cartões"
SCH = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VIS_SCHEMA = f"{SCH}/visualContainer/2.0.0/schema.json"
M = "_Medidas"
CS = "card_scores"
_z = itertools.count(1000, 1000)


def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + v.replace("'", "''") + "'"}}}


def measure(name):
    return ("Measure", M, name)


def col(table, name):
    return ("Column", table, name)


def field(f):
    kind, table, name = f
    return {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def qref(f):
    return f"{f[1]}.{f[2]}"


def title(text, align=None):
    props = {"show": lit(True), "text": lit(text)}
    if align:
        props["alignment"] = lit(align)
    return {"title": [{"properties": props}],
            "subTitle": [{"properties": {"show": lit(False)}}]}


NOMES = {"operador_display": "Operadora", "rank": "Rank", "nome": "Nome", "card_id": "Cartão",
         "anomaly_score": "Score", "cluster": "Cluster", "motivo_principal": "Motivo principal",
         "trajeto": "Linha", "tipo_linha": "Tipo de linha", "decil_score": "Decil do score", "InicioMes": "Mês"}

# Grade da página (1280 × 720): margem de 16 px e 12 px entre blocos; tudo encosta nas mesmas linhas.
MARGEM, GAP, LARGURA_UTIL = 16, 12, 1248
TOPO_FILTRO, ALT_FILTRO = 6, 70            # faixa do título e dos filtros
TOPO_CARTAO, ALT_CARTAO = 88, 92           # faixa dos cartões
TOPO_CORPO, BASE = 192, 704                # corpo da página até a margem de baixo


def colunas(n, de=MARGEM, ate=MARGEM + LARGURA_UTIL):
    """x e largura de n colunas iguais entre `de` e `ate`."""
    w = (ate - de - GAP * (n - 1)) / n
    return [round(de + i * (w + GAP)) for i in range(n)], round(w)


def larguras_coluna(px):
    """Largura fixa por coluna de tabela (queryRef -> px): sem rolagem horizontal nem coluna cortada."""
    return [{"properties": {"value": lit(v)}, "selector": {"metadata": ref}} for ref, v in px.items()]


class Page:
    def __init__(self, name, display):
        self.name, self.display, self.visuals = name, display, {}

    def _add(self, x, y, w, h, visual, filters=None):
        vname = f"{self.name}_{len(self.visuals) + 1:02d}"
        z = next(_z)
        doc = {"$schema": VIS_SCHEMA, "name": vname,
               "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
               "visual": visual}
        if filters:
            doc["filterConfig"] = {"filters": filters}
        self.visuals[vname] = doc

    def visual(self, vtype, x, y, w, h, roles, text=None, sort=None, objects=None, filters=None,
               nomes=None, align=None):
        state = {}
        for role, fields in roles.items():
            projs = []
            for i, f in enumerate(fields):
                p = {"field": field(f), "queryRef": qref(f), "nativeQueryRef": f[2]}
                nome = (nomes or {}).get(f[2], NOMES.get(f[2]))
                if nome:
                    p["displayName"] = nome
                if role == "Category" and i == 0:
                    p["active"] = True
                projs.append(p)
            state[role] = {"projections": projs}
        query = {"queryState": state}
        if sort:
            f, direction = sort
            query["sortDefinition"] = {"sort": [{"field": field(f), "direction": direction}], "isDefaultSort": True}
        v = {"visualType": vtype, "query": query, "drillFilterOtherVisuals": True}
        if objects:
            v["objects"] = objects
        if text:
            v["visualContainerObjects"] = title(text, align)
        self._add(x, y, w, h, v, filters)

    def textbox(self, x, y, w, h, text, size="20pt", bold=True, color=TXT, sub=None):
        style = {"fontSize": size, "color": color}
        if bold:
            style["fontWeight"] = "bold"
        paras = [{"textRuns": [{"value": text, "textStyle": style}]}]
        if sub:
            paras.append({"textRuns": [{"value": sub, "textStyle": {"fontSize": "10pt", "color": TXT2}}]})
        v = {"visualType": "textbox", "drillFilterOtherVisuals": True,
             "objects": {"general": [{"properties": {"paragraphs": paras}}]}}
        self._add(x, y, w, h, v)

    def cabecalho(self, w, text):
        self.textbox(MARGEM, TOPO_FILTRO + 2, w, ALT_FILTRO - 4, text, size="18pt", sub=SUBTITULO)

    def card(self, x, y, m, w, h=ALT_CARTAO):
        # título e valor centralizados na caixa
        self.visual("card", x, y, w, h, {"Values": [measure(m)]}, text=m, align="center",
                    objects={"categoryLabels": [{"properties": {"show": lit(False)}}]})

    def cartoes(self, medidas):
        xs, w = colunas(len(medidas))
        for x, m in zip(xs, medidas):
            self.card(x, TOPO_CARTAO, m, w)

    def slicer(self, x, f, text, w):
        # cabeçalho do próprio filtro (e não o título do visual): sobra altura para a lista suspensa
        self.visual("slicer", x, TOPO_FILTRO, w, ALT_FILTRO, {"Values": [f]}, nomes={f[2]: text},
                    objects={"data": [{"properties": {"mode": lit("Dropdown")}}],
                             "header": [{"properties": {"show": lit(True)}}]})


def cat_filter(table, column, values):
    return [{
        "name": f"flt_{table}_{column}",
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}},
        "type": "Categorical",
        "filter": {"Version": 2,
                   "From": [{"Name": "t", "Entity": table, "Type": 0}],
                   "Where": [{"Condition": {"In": {
                       "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}],
                       "Values": [[{"Literal": {"Value": "'" + v + "'"}}] for v in values]}}}]}}]


def topn_filter(table, column, medida, n):
    """Filtro de visual "Top N" de `column` pela medida (ex.: as 8 linhas com mais embarques)."""
    coluna = {"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": column}}
    return [{
        "name": f"top_{table}_{column}",
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}},
        "type": "TopN",
        "filter": {"Version": 2,
                   "From": [{"Name": "sub", "Type": 2, "Expression": {"Subquery": {"Query": {
                       "Version": 2,
                       "From": [{"Name": "t", "Entity": table, "Type": 0}, {"Name": "m", "Entity": M, "Type": 0}],
                       "Select": [dict(coluna, Name="field")],
                       "OrderBy": [{"Direction": 2, "Expression": {"Measure": {
                           "Expression": {"SourceRef": {"Source": "m"}}, "Property": medida}}}],
                       "Top": n}}}},
                            {"Name": "t", "Entity": table, "Type": 0}],
                   "Where": [{"Condition": {"In": {"Expressions": [coluna],
                                                    "Table": {"SourceRef": {"Source": "sub"}}}}}]}}]


ANO = col("dim_calendario", "Ano")
ANOMES = col("dim_calendario", "InicioMes")
OPER = col("dim_linha", "operador_display")
EM_ALERTA = cat_filter(CS, "status_alerta", ["Em alerta"])
ROTULOS = {"labels": [{"properties": {"show": lit(True)}}]}
# eixo de categorias das barras com até metade da largura: nomes longos de linha e de motivo não cortam
EIXO_LARGO = {"categoryAxis": [{"properties": {"maxMarginFactor": lit(50)}}]}

# ---------------- Operação ----------------
p1 = Page("operacao", "Operação")
c5, w5 = colunas(5)
p1.cabecalho(c5[3] - MARGEM - GAP, "Operação — embarques e receita")
p1.slicer(c5[3], ANO, "Ano", w5)
p1.slicer(c5[4], OPER, "Operadora", w5)
p1.cartoes(["Embarques", "Receita", "Ticket Médio", "Cartões Ativos", "Recarregado"])
alt_meio = 212
meio = TOPO_CORPO + alt_meio
p1.visual("lineChart", c5[0], TOPO_CORPO, c5[3] - GAP - c5[0], alt_meio, {"Category": [ANOMES],
          "Y": [measure("Embarques"), measure("Embarques Média Móvel 3M")]},
          text="Embarques por mês e média móvel 3M", sort=(ANOMES, "Ascending"))
p1.visual("clusteredBarChart", c5[3], TOPO_CORPO, c5[4] + w5 - c5[3], alt_meio,
          {"Category": [col("dim_linha", "tipo_linha")], "Y": [measure("Receita")]},
          text="Receita por tipo de linha", sort=(measure("Receita"), "Descending"),
          # milhões com 1 casa: o intermunicipal (R$ 0,2M) não some como "R$ 0M"
          objects={"labels": [{"properties": {"show": lit(True), "labelDisplayUnits": lit(1000000),
                                              "labelPrecision": lit(1)}}]})
p1.visual("clusteredBarChart", c5[0], meio + GAP, c5[2] - GAP - c5[0], BASE - meio - GAP,
          {"Category": [col("dim_linha", "trajeto")], "Y": [measure("Embarques")]},
          text="Top 8 linhas por embarques", sort=(measure("Embarques"), "Descending"),
          objects=dict(EIXO_LARGO, **ROTULOS), filters=topn_filter("dim_linha", "trajeto", "Embarques", 8))
p1.visual("tableEx", c5[2], meio + GAP, c5[4] + w5 - c5[2], BASE - meio - GAP,
          {"Values": [OPER, measure("Embarques"), measure("Receita"), measure("Ticket Médio"),
                      measure("% Embarques Noturnos"), measure("% Erros de Validador")]},
          text="Operadoras", sort=(measure("Embarques"), "Descending"),
          nomes={"% Embarques Noturnos": "% noturnos", "% Erros de Validador": "% erros"},
          objects={"columnWidth": larguras_coluna({
              "dim_linha.operador_display": 140, f"{M}.Embarques": 110, f"{M}.Receita": 160,
              f"{M}.Ticket Médio": 110, f"{M}.% Embarques Noturnos": 100, f"{M}.% Erros de Validador": 90})})

# ---------------- Fila de auditoria ----------------
p2 = Page("fila", "Fila de auditoria")
c4, w4 = colunas(4)
p2.cabecalho(c4[2] - MARGEM - GAP, "Fila de auditoria — cartões priorizados")
p2.slicer(c4[2], col(CS, "cluster"), "Cluster", w4)
p2.slicer(c4[3], col(CS, "motivo_principal"), "Motivo principal", w4)
p2.cartoes(["Cartões em Alerta", "% Cartões em Alerta", "Receita em Cartões em Alerta", "Score Médio"])
c12, w12 = colunas(12)
# tabela com 800 px: nome, cartão e motivo cabem numa linha (com a barra de rolagem vertical)
x_dir = MARGEM + 800 + GAP
p2.visual("tableEx", MARGEM, TOPO_CORPO, 800, BASE - TOPO_CORPO,
          {"Values": [col(CS, "rank"), col(CS, "nome"), col(CS, "card_id"),
                      col(CS, "anomaly_score"), col(CS, "motivo_principal")]},
          text="Fila — cartões em alerta por rank", sort=(col(CS, "rank"), "Ascending"), filters=EM_ALERTA,
          objects={"columnWidth": larguras_coluna({
              f"{CS}.rank": 52, f"{CS}.nome": 238, f"{CS}.card_id": 126, f"{CS}.anomaly_score": 64,
              f"{CS}.motivo_principal": 276})})
corte = TOPO_CORPO + 280
p2.visual("clusteredBarChart", x_dir, TOPO_CORPO, MARGEM + LARGURA_UTIL - x_dir, 280,
          {"Category": [col(CS, "motivo_principal")], "Y": [measure("Cartões em Alerta")]},
          text="Top 8 motivos dos alertas", sort=(measure("Cartões em Alerta"), "Descending"),
          # 24 motivos não cabem: os 8 mais frequentes, com fonte 9 e até 72% da largura para o nome
          filters=EM_ALERTA + topn_filter(CS, "motivo_principal", "Cartões em Alerta", 8),
          objects={"categoryAxis": [{"properties": {"maxMarginFactor": lit(72), "fontSize": lit(9)}}], **ROTULOS})
p2.visual("lineChart", x_dir, corte + GAP, MARGEM + LARGURA_UTIL - x_dir, BASE - corte - GAP,
          {"Category": [ANOMES], "Y": [measure("Cartões Ativos em Alerta")]},
          text="Cartões em alerta com uso no mês", sort=(ANOMES, "Ascending"))

# ---------------- Perfis ----------------
p3 = Page("perfis", "Perfis")
p3.cabecalho(900, "Perfis de uso — clusters")
x_dir = c12[7]                                    # dispersão em 7 colunas, tabela e barras em 5
topo = TOPO_CARTAO
p3.visual("scatterChart", MARGEM, topo, x_dir - GAP - MARGEM, BASE - topo,
          {"Category": [col(CS, "cluster")], "Series": [col(CS, "cluster")],
           "X": [measure("Score Médio")], "Y": [measure("% Cartões em Alerta")], "Size": [measure("Cartões")]},
          text="Clusters: score médio × % em alerta (tamanho = cartões)",
          objects={"categoryLabels": [{"properties": {"show": lit(True)}}],
                   "legend": [{"properties": {"showTitle": lit(True), "titleText": lit("Cluster")}}]})
alt_tab = 214
corte = topo + alt_tab
p3.visual("tableEx", x_dir, topo, MARGEM + LARGURA_UTIL - x_dir, alt_tab,
          {"Values": [col(CS, "cluster"), measure("Cartões"), measure("% Cartões em Alerta"),
                      measure("Score Médio"), measure("Embarques por Cartão Ativo"), measure("% Embarques Noturnos")]},
          text="Resumo por cluster", sort=(col(CS, "cluster"), "Ascending"),
          nomes={"% Cartões em Alerta": "% em alerta", "Score Médio": "Score médio",
                 "Embarques por Cartão Ativo": "Emb./cartão", "% Embarques Noturnos": "% noite"},
          objects={"columnWidth": larguras_coluna({
              f"{CS}.cluster": 60, f"{M}.Cartões": 68, f"{M}.% Cartões em Alerta": 88, f"{M}.Score Médio": 92,
              f"{M}.Embarques por Cartão Ativo": 96, f"{M}.% Embarques Noturnos": 72})})
p3.visual("clusteredColumnChart", x_dir, corte + GAP, MARGEM + LARGURA_UTIL - x_dir, BASE - corte - GAP,
          {"Category": [col(CS, "cluster")], "Y": [measure("Cartões em Alerta")]}, text="Cartões em alerta por cluster",
          sort=(col(CS, "cluster"), "Ascending"),
          objects=dict({"categoryAxis": [{"properties": {"axisType": lit("Categorical")}}]}, **ROTULOS))

# ---------------- Qualidade do modelo ----------------
p4 = Page("qualidade", "Qualidade do modelo")
p4.cabecalho(1000, "Qualidade do modelo (somente cartões com rótulo)")
p4.cartoes(["Precisão da Fila", "Recall da Fila", "Taxa de Fraude", "Fraudes Reais", "Cartões Rotulados"])
alt = 444
p4.visual("lineClusteredColumnComboChart", MARGEM, TOPO_CORPO, LARGURA_UTIL, alt,
          {"Category": [col(CS, "decil_score")], "Y": [measure("Cartões Rotulados")], "Y2": [measure("Taxa de Fraude")]},
          text="Taxa de fraude por decil de anomaly_score (10 = mais anômalos)",
          sort=(col(CS, "decil_score"), "Ascending"),
          objects={"categoryAxis": [{"properties": {"axisType": lit("Categorical")}}],
                   # eixo da taxa até 100%: os decis 9 e 10 passam de 50% e a linha saía do gráfico
                   "valueAxis": [{"properties": {"secStart": lit(0), "secEnd": lit(1)}}],
                   "lineStyles": [{"properties": {"lineChartType": lit("linear")}}],
                   # rótulo só na taxa: as colunas são todas 250 e escondiam o valor do decil 10
                   "labels": [{"properties": {"show": lit(True)}},
                              {"properties": {"show": lit(False)}, "selector": {"metadata": f"{M}.Cartões Rotulados"}}]})
p4.textbox(MARGEM, TOPO_CORPO + alt + GAP, LARGURA_UTIL, BASE - TOPO_CORPO - alt - GAP,
           "Leitura: a Precisão da Fila deve ficar bem acima da Taxa de Fraude base; se a taxa por decil for plana, "
           "o score não está separando fraude de uso normal. Cartões sem rótulo (dados reais) ficam fora destas métricas.",
           size="11pt", bold=False, color=TXT2)

PAGES = [p1, p2, p3, p4]


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


# limpa formato legado / definição anterior
for p in ["report.json", "definition"]:
    fp = os.path.join(REPORT_DIR, p)
    if os.path.isdir(fp):
        shutil.rmtree(fp)
    elif os.path.exists(fp):
        os.remove(fp)

write(os.path.join(REPORT_DIR, "definition.pbir"), {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
    "version": "4.0",
    "datasetReference": {"byPath": {"path": "../Fila de Auditoria.SemanticModel"}}})
D = os.path.join(REPORT_DIR, "definition")
write(os.path.join(D, "version.json"), {"$schema": f"{SCH}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
write(os.path.join(D, "report.json"), {
    "$schema": f"{SCH}/report/3.3.0/schema.json",
    "themeCollection": {"baseTheme": {"name": THEME,
                                      "reportVersionAtImport": {"visual": "2.12.0", "report": "3.4.0", "page": "2.3.1"},
                                      "type": "SharedResources"},
                        "customTheme": {"name": CUSTOM,
                                        "reportVersionAtImport": {"visual": "2.12.0", "report": "3.4.0", "page": "2.3.1"},
                                        "type": "RegisteredResources"}},
    "objects": {"section": [{"properties": {"verticalAlignment": lit("Top")}}]},
    "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                          "items": [{"name": THEME, "path": f"BaseThemes/{THEME}.json", "type": "BaseTheme"}]},
                         {"name": "RegisteredResources", "type": "RegisteredResources",
                          "items": [{"name": CUSTOM, "path": CUSTOM, "type": "CustomTheme"}]}],
    "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                 "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                 "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}})
write(os.path.join(D, "pages", "pages.json"), {"$schema": f"{SCH}/pagesMetadata/1.1.0/schema.json",
                                               "pageOrder": [p.name for p in PAGES], "activePageName": PAGES[0].name})
for p in PAGES:
    pd = os.path.join(D, "pages", p.name)
    write(os.path.join(pd, "page.json"), {"$schema": f"{SCH}/page/2.1.0/schema.json", "name": p.name,
                                          "displayName": p.display, "displayOption": "FitToPage",
                                          "height": 720, "width": 1280})
    for vname, doc in p.visuals.items():
        write(os.path.join(pd, "visuals", vname, "visual.json"), doc)

theme_dst = os.path.join(REPORT_DIR, "StaticResources", "SharedResources", "BaseThemes", f"{THEME}.json")
os.makedirs(os.path.dirname(theme_dst), exist_ok=True)
if os.path.abspath(THEME_SRC) != os.path.abspath(theme_dst):
    shutil.copyfile(THEME_SRC, theme_dst)
custom_dst = os.path.join(REPORT_DIR, "StaticResources", "RegisteredResources", CUSTOM)
os.makedirs(os.path.dirname(custom_dst), exist_ok=True)
shutil.copyfile(CUSTOM_SRC, custom_dst)
print("ok:", len(PAGES), "páginas,", sum(len(p.visuals) for p in PAGES), "visuais")
