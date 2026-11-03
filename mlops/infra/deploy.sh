#!/usr/bin/env bash
# Deploy completo no Azure. Pré-requisitos: az login, databricks CLI autenticado no workspace
# (databricks auth login --host <url>, depois do passo 1), extensão `az extension add -n datafactory`, jq.
# Docker local para publicar a imagem da API. Nada aqui roda sozinho no CI: é o roteiro do primeiro deploy.
#
#   RG=rg-smart-ticket-fraud LOCATION=brazilsouth ./mlops/infra/deploy.sh
#
# Azure for Students: DBW_SKU=trial (padrão) zera o DBU por 14 dias; depois, DBW_SKU=premium no mesmo
# comando converte o workspace. O job cluster é de nó único Standard_D4ds_v4 (4 vCPU, família DDSv4).
set -euo pipefail

RG=${RG:-rg-smart-ticket-fraud}
LOCATION=${LOCATION:-brazilsouth}
PREFIX=${PREFIX:-stf}
CATALOG=${CATALOG:-smart_ticket}
DBW_SKU=${DBW_SKU:-trial}
GITHUB_REPO=${GITHUB_REPO:-IgorClau/smart-ticket-fraud-detection}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OPERADOR=$(az ad signed-in-user show --query id -o tsv)
PARAMS=(prefix="$PREFIX" operatorPrincipalId="$OPERADOR" databricksSku="$DBW_SKU" githubRepo="$GITHUB_REPO")

echo "==> 0/7 cota de vCPU em $LOCATION (o job cluster precisa de 4 vCPU livres na família DDSv4)"
livre() { az vm list-usage -l "$LOCATION" --query "[?name.value=='$1'] | [0].[limit, currentValue]" -o tsv \
          | tr -s '\t\n' '  ' | awk '{print $1 - $2}'; }
for fam in cores standardDDSv4Family; do
  if [ "$(livre "$fam")" -lt 4 ]; then
    echo "Cota insuficiente em $fam ($LOCATION): peça aumento em Assinaturas > Uso + cotas ou troque LOCATION." >&2
    exit 1
  fi
done

echo "==> 1/7 grupo de recursos e infraestrutura (Bicep)"
az group create -n "$RG" -l "$LOCATION" -o none
OUT=$(az deployment group create -g "$RG" -f "$ROOT/mlops/infra/main.bicep" \
      -p "${PARAMS[@]}" --query properties.outputs -o json)
STORAGE=$(jq -r .storageAccount.value <<<"$OUT")
ADF=$(jq -r .dataFactory.value <<<"$OUT")
ACR=$(jq -r .acrLoginServer.value <<<"$OUT")
DBW_URL=$(jq -r .databricksUrl.value <<<"$OUT")
DBW_NAME=$(jq -r .databricksWorkspace.value <<<"$OUT")
CONNECTOR=$(jq -r .accessConnectorId.value <<<"$OUT")
ADF_APP=$(az ad sp show --id "$(jq -r .dataFactoryPrincipalId.value <<<"$OUT")" --query appId -o tsv)
export DATABRICKS_HOST="$DBW_URL"

echo "==> 2/7 imagem da API no ACR e nova revisão do Container Apps"
# Build local + push: o build remoto do ACR (ACR Tasks) costuma vir bloqueado em assinaturas de crédito gratuito.
az acr login --name "${ACR%%.*}"
docker build -f "$ROOT/docker/Dockerfile" -t "$ACR/stf-api:latest" "$ROOT"
docker push "$ACR/stf-api:latest"
az deployment group create -g "$RG" -f "$ROOT/mlops/infra/main.bicep" \
   -p "${PARAMS[@]}" apiImage="$ACR/stf-api:latest" -o none

echo "==> 3/7 repositório no Databricks (Git folder)"
# Repositório privado: antes, `databricks git-credentials create gitHub --git-username <usuário>
# --personal-access-token <PAT só com leitura do repo>` (uma vez por workspace).
databricks repos create "https://github.com/$GITHUB_REPO" gitHub \
   --path /Repos/smart-ticket-fraud-detection || echo "repo já existe"

echo "==> 4/7 Unity Catalog: credencial, locais externos, catálogo, schemas e permissões do ADF"
# O access connector (identidade gerenciada com Storage Blob Data Contributor) é a credencial do lake.
databricks storage-credentials create --json \
  "{\"name\": \"stf_lake\", \"azure_managed_identity\": {\"access_connector_id\": \"$CONNECTOR\"}}" || echo "credencial já existe"
for c in raw lakehouse; do
  databricks external-locations create "stf_$c" "abfss://$c@$STORAGE.dfs.core.windows.net/" stf_lake || echo "stf_$c já existe"
done
databricks catalogs create "$CATALOG" --storage-root "abfss://lakehouse@$STORAGE.dfs.core.windows.net/uc" || echo "catálogo já existe"
for s in bronze silver gold; do databricks schemas create "$s" "$CATALOG" || echo "schema $s já existe"; done
# A MSI do ADF dispara os jobs: precisa existir no workspace e ter acesso ao catálogo e aos locais externos.
databricks service-principals create --json "{\"application_id\": \"$ADF_APP\", \"display_name\": \"$ADF\"}" \
  || echo "service principal já existe"
databricks grants update catalog "$CATALOG" --json "{\"changes\": [{\"principal\": \"$ADF_APP\", \"add\": [\"ALL_PRIVILEGES\"]}]}"
for c in raw lakehouse; do
  databricks grants update external_location "stf_$c" \
    --json "{\"changes\": [{\"principal\": \"$ADF_APP\", \"add\": [\"READ_FILES\", \"WRITE_FILES\", \"CREATE_EXTERNAL_TABLE\"]}]}"
done
# Job clusters do ADF: nó único, modo dedicado à MSI do ADF (compatível com Unity Catalog). A política é
# referenciada no linked service; reaplicada a cada deploy para acompanhar mlops/infra/cluster_policy.json.
POLICY_DEF=$(sed "s#<adf-app-id>#$ADF_APP#g" "$ROOT/mlops/infra/cluster_policy.json" | jq -c .)
POLICY_ID=$(databricks cluster-policies list -o json | jq -r '.[] | select(.name == "stf-uc-jobs") | .policy_id')
if [ -z "$POLICY_ID" ]; then
  POLICY_ID=$(databricks cluster-policies create --name stf-uc-jobs --definition "$POLICY_DEF" -o json | jq -r .policy_id)
else
  databricks cluster-policies edit "$POLICY_ID" --name stf-uc-jobs --definition "$POLICY_DEF"
fi

echo "==> 5/7 artefatos do Data Factory (placeholders trocados pelos nomes reais)"
TMP=$(mktemp -d)
for f in "$ROOT"/mlops/adf/*/*.json; do
  sed -e "s#stfdatalake#$STORAGE#g" -e "s#https://adb-0000000000000000.0.azuredatabricks.net#$DBW_URL#g" \
      -e "s#<subscription-id>#$(az account show --query id -o tsv)#g" -e "s#rg-smart-ticket-fraud#$RG#g" \
      -e "s#workspaces/dbw-smart-ticket-fraud#workspaces/$DBW_NAME#g" -e "s#<cluster-policy-id>#$POLICY_ID#g" \
      -e "s#\"defaultValue\": \"smart_ticket\"#\"defaultValue\": \"$CATALOG\"#g" \
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

echo "==> 6/7 carga inicial: extratos gerados -> landing (RBAC de dados do operador, sem chave)"
az storage blob upload-batch --auth-mode login --account-name "$STORAGE" -d landing/viacard \
   -s "$ROOT/data/raw/viacard_v44" --overwrite

echo "==> 7/7 primeira execução do pipeline"
az datafactory pipeline create-run -g "$RG" --factory-name "$ADF" -n pl_medallion_smart_ticket
echo "Pronto. API: $(jq -r .apiUrl.value <<<"$OUT")"
echo "CI (GitHub > Settings > Environments > production): AZURE_CLIENT_ID=$(jq -r .ciClientId.value <<<"$OUT")" \
     "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv) AZURE_SUBSCRIPTION_ID=$(az account show --query id -o tsv);" \
     "variáveis ACR_NAME=${ACR%%.*} CONTAINERAPP_NAME=$(jq -r .containerApp.value <<<"$OUT") RESOURCE_GROUP=$RG AZURE_DEPLOY=true"
echo "dbt no Azure: DATABRICKS_HOST=${DBW_URL#https://} DATABRICKS_CATALOG=$CATALOG + HTTP_PATH/TOKEN de um SQL Warehouse"
