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


def title(text):
    return {"title": [{"properties": {"show": lit(True), "text": lit(text)}}],
            "subTitle": [{"properties": {"show": lit(False)}}]}


NOMES = {"operador_display": "Operadora", "rank": "Rank", "nome": "Nome", "card_id": "Cartão",
         "anomaly_score": "Score", "cluster": "Cluster", "motivo_principal": "Motivo principal",
         "trajeto": "Linha", "tipo_linha": "Tipo de linha", "decil_score": "Decil do score", "InicioMes": "Mês"}


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

    def visual(self, vtype, x, y, w, h, roles, text=None, sort=None, objects=None, filters=None):
        state = {}
        for role, fields in roles.items():
            projs = []
            for i, f in enumerate(fields):
                p = {"field": field(f), "queryRef": qref(f), "nativeQueryRef": f[2]}
                if f[2] in NOMES:
                    p["displayName"] = NOMES[f[2]]
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
            v["visualContainerObjects"] = title(text)
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
        self.textbox(16, 2, w, 66, text, size="18pt", sub=SUBTITULO)

    def card(self, x, y, m, w=236, h=100):
        self.visual("card", x, y, w, h, {"Values": [measure(m)]}, text=m,
                    objects={"categoryLabels": [{"properties": {"show": lit(False)}}]})

    def slicer(self, x, y, f, text, w=200, h=64):
        self.visual("slicer", x, y, w, h, {"Values": [f]}, text=text,
                    objects={"data": [{"properties": {"mode": lit("Dropdown")}}],
                             "header": [{"properties": {"show": lit(False)}}]})


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


ANO = col("dim_calendario", "Ano")
ANOMES = col("dim_calendario", "InicioMes")
OPER = col("dim_linha", "operador_display")
EM_ALERTA = cat_filter(CS, "status_alerta", ["Em alerta"])

# ---------------- Operação ----------------
p1 = Page("operacao", "Operação")
p1.cabecalho(640, "Operação — embarques e receita")
p1.slicer(852, 4, ANO, "Ano")
p1.slicer(1064, 4, OPER, "Operadora")
for i, m in enumerate(["Embarques", "Receita", "Ticket Médio", "Cartões Ativos", "Recarregado"]):
    p1.card(16 + i * 250, 76, m)
p1.visual("lineChart", 16, 192, 820, 260, {"Category": [ANOMES],
          "Y": [measure("Embarques"), measure("Embarques Média Móvel 3M")]},
          text="Embarques por mês e média móvel 3M", sort=(ANOMES, "Ascending"))
p1.visual("clusteredColumnChart", 852, 192, 412, 260, {"Category": [col("dim_linha", "tipo_linha")],
          "Y": [measure("Receita")]}, text="Receita por tipo de linha", sort=(measure("Receita"), "Descending"))
p1.visual("clusteredBarChart", 16, 468, 620, 236, {"Category": [col("dim_linha", "trajeto")],
          "Y": [measure("Embarques")]}, text="Linhas por embarques", sort=(measure("Embarques"), "Descending"))
p1.visual("tableEx", 652, 468, 612, 236, {"Values": [OPER, measure("Embarques"), measure("Receita"),
          measure("Ticket Médio"), measure("% Embarques Noturnos"), measure("% Erros de Validador")]},
          text="Operadoras", sort=(measure("Embarques"), "Descending"))

# ---------------- Fila de auditoria ----------------
p2 = Page("fila", "Fila de auditoria")
p2.cabecalho(620, "Fila de auditoria — cartões priorizados")
p2.slicer(652, 4, col(CS, "cluster"), "Cluster", w=190)
p2.slicer(852, 4, col(CS, "motivo_principal"), "Motivo principal", w=412)
for i, m in enumerate(["Cartões em Alerta", "% Cartões em Alerta", "Receita em Cartões em Alerta", "Score Médio"]):
    p2.card(16 + i * 312, 76, m, w=300)
p2.visual("tableEx", 16, 192, 820, 512, {"Values": [col(CS, "rank"), col(CS, "nome"), col(CS, "card_id"),
          col(CS, "anomaly_score"), col(CS, "cluster"), col(CS, "motivo_principal")]},
          text="Fila — cartões em alerta por rank", sort=(col(CS, "rank"), "Ascending"), filters=EM_ALERTA)
p2.visual("clusteredBarChart", 852, 192, 412, 256, {"Category": [col(CS, "motivo_principal")],
          "Y": [measure("Cartões em Alerta")]}, text="Motivo principal dos alertas",
          sort=(measure("Cartões em Alerta"), "Descending"), filters=EM_ALERTA)
p2.visual("lineChart", 852, 464, 412, 240, {"Category": [ANOMES], "Y": [measure("Cartões Ativos em Alerta")]},
          text="Cartões em alerta com uso no mês", sort=(ANOMES, "Ascending"))

# ---------------- Perfis ----------------
p3 = Page("perfis", "Perfis")
p3.cabecalho(640, "Perfis de uso — clusters")
p3.visual("scatterChart", 16, 68, 700, 636, {"Category": [col(CS, "cluster")], "Series": [col(CS, "cluster")],
          "X": [measure("Score Médio")], "Y": [measure("% Cartões em Alerta")], "Size": [measure("Cartões")]},
          text="Clusters: score médio × % em alerta (tamanho = cartões)")
p3.visual("tableEx", 732, 68, 532, 300, {"Values": [col(CS, "cluster"), measure("Cartões"),
          measure("% Cartões em Alerta"), measure("Score Médio"), measure("Embarques por Cartão Ativo"),
          measure("% Embarques Noturnos")]}, text="Resumo por cluster", sort=(col(CS, "cluster"), "Ascending"))
p3.visual("clusteredColumnChart", 732, 384, 532, 320, {"Category": [col(CS, "cluster")],
          "Y": [measure("Cartões em Alerta")]}, text="Cartões em alerta por cluster",
          sort=(col(CS, "cluster"), "Ascending"), objects={"categoryAxis": [{"properties": {"axisType": lit("Categorical")}}]})

# ---------------- Qualidade do modelo ----------------
p4 = Page("qualidade", "Qualidade do modelo")
p4.cabecalho(900, "Qualidade do modelo (somente cartões com rótulo)")
for i, m in enumerate(["Precisão da Fila", "Recall da Fila", "Taxa de Fraude", "Fraudes Reais", "Cartões Rotulados"]):
    p4.card(16 + i * 250, 68, m)
p4.visual("lineClusteredColumnComboChart", 16, 184, 1248, 420, {"Category": [col(CS, "decil_score")],
          "Y": [measure("Cartões Rotulados")], "Y2": [measure("Taxa de Fraude")]},
          text="Taxa de fraude por decil de anomaly_score (10 = mais anômalos)",
          sort=(col(CS, "decil_score"), "Ascending"),
          objects={"categoryAxis": [{"properties": {"axisType": lit("Categorical")}}],
                   # eixo da taxa até 100%: os decis 9 e 10 passam de 50% e a linha saía do gráfico
                   "valueAxis": [{"properties": {"secStart": lit(0), "secEnd": lit(1)}}],
                   "lineStyles": [{"properties": {"lineChartType": lit("linear")}}],
                   "labels": [{"properties": {"show": lit(True)}}]})
p4.textbox(16, 620, 1248, 84,
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
