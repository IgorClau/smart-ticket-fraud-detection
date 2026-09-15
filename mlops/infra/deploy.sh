#!/usr/bin/env bash
# Deploy completo no Azure. Pré-requisitos: az login, databricks CLI autenticado, extensão
# `az extension add -n datafactory`, jq. Nada aqui roda sozinho no CI: é o roteiro do primeiro deploy.
#
#   RG=rg-smart-ticket-fraud LOCATION=brazilsouth ./mlops/infra/deploy.sh
set -euo pipefail

RG=${RG:-rg-smart-ticket-fraud}
LOCATION=${LOCATION:-brazilsouth}
PREFIX=${PREFIX:-stf}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

echo "==> 1/6 grupo de recursos e infraestrutura (Bicep)"
az group create -n "$RG" -l "$LOCATION" -o none
OUT=$(az deployment group create -g "$RG" -f "$ROOT/mlops/infra/main.bicep" -p prefix="$PREFIX" \
      --query properties.outputs -o json)
STORAGE=$(jq -r .storageAccount.value <<<"$OUT")
ADF=$(jq -r .dataFactory.value <<<"$OUT")
ACR=$(jq -r .acrLoginServer.value <<<"$OUT")
DBW_URL=$(jq -r .databricksUrl.value <<<"$OUT")

echo "==> 2/6 imagem da API no ACR e nova revisão do Container Apps"
az acr build --registry "${ACR%%.*}" --image stf-api:latest --file "$ROOT/docker/Dockerfile" "$ROOT"
az deployment group create -g "$RG" -f "$ROOT/mlops/infra/main.bicep" \
   -p prefix="$PREFIX" apiImage="$ACR/stf-api:latest" -o none

echo "==> 3/6 repositório no Databricks (Git folder)"
databricks repos create "https://github.com/<usuario>/smart-ticket-fraud-detection" gitHub \
   --path /Repos/smart-ticket-fraud-detection || echo "repo já existe"

echo "==> 4/6 artefatos do Data Factory (placeholders trocados pelos nomes reais)"
TMP=$(mktemp -d)
for f in "$ROOT"/mlops/adf/*/*.json; do
  sed -e "s#stfdatalake#$STORAGE#g" -e "s#https://adb-0000000000000000.0.azuredatabricks.net#$DBW_URL#g" \
      -e "s#<subscription-id>#$(az account show --query id -o tsv)#g" -e "s#rg-smart-ticket-fraud#$RG#g" \
      "$f" > "$TMP/$(basename "$f")"
done
az datafactory linked-service create -g "$RG" --factory-name "$ADF" -n ls_adls_lake \
   --properties "$(jq .properties "$TMP/ls_adls_lake.json")"
az datafactory linked-service create -g "$RG" --factory-name "$ADF" -n ls_databricks \
   --properties "$(jq .properties "$TMP/ls_databricks.json")"
for ds in ds_landing_extratos ds_raw_extratos; do
  az datafactory dataset create -g "$RG" --factory-name "$ADF" -n "$ds" --properties "$(jq .properties "$TMP/$ds.json")"
done
az datafactory pipeline create -g "$RG" --factory-name "$ADF" -n pl_medallion_smart_ticket \
   --pipeline "$(jq .properties "$TMP/pl_medallion_smart_ticket.json")"
az datafactory trigger create -g "$RG" --factory-name "$ADF" -n tr_diario_0200 \
   --properties "$(jq .properties "$TMP/tr_diario_0200.json")"

echo "==> 5/6 carga inicial: extratos gerados -> landing"
az storage blob upload-batch --auth-mode login --account-name "$STORAGE" -d landing/viacard \
   -s "$ROOT/data/raw/viacard_v44" --overwrite

echo "==> 6/6 primeira execução do pipeline"
az datafactory pipeline create-run -g "$RG" --factory-name "$ADF" -n pl_medallion_smart_ticket
echo "Pronto. API: $(jq -r .apiUrl.value <<<"$OUT")"
