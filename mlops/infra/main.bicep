// Infraestrutura do Smart Ticket Fraud Detection (Azure).
//   az deployment group create -g rg-smart-ticket-fraud -f mlops/infra/main.bicep -p prefix=stf
//
// Recursos: ADLS Gen2 (landing/raw/lakehouse) · Data Factory (MSI) · Databricks (premium) + access
// connector · Container Registry · Log Analytics · Container Apps (API, escala a zero).
// Todo acesso entre serviços é por identidade gerenciada + RBAC — nenhuma chave em configuração.

@description('Prefixo curto (3-8 letras minúsculas) usado nos nomes.')
@minLength(3)
@maxLength(8)
param prefix string = 'stf'

param location string = resourceGroup().location

@description('Imagem da API. No primeiro deploy use a imagem pública de exemplo; o CI troca pela do ACR.')
param apiImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Object ID de quem opera o projeto (az ad signed-in-user show --query id). Recebe acesso de dados ao lake para a carga inicial; vazio = nenhum.')
param operatorPrincipalId string = ''

var suffix = uniqueString(resourceGroup().id)
var storageName = toLower('${prefix}lake${take(suffix, 8)}')
var roles = {
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  contributor: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

// ---------------------------------------------------------------- data lake
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in ['landing', 'raw', 'lakehouse']: {
  parent: blob
  name: c
}]

// Sem chave compartilhada, nem o dono da assinatura grava no lake: acesso a dados exige RBAC de dados.
resource operatorLake 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  name: guid(storage.id, operatorPrincipalId, roles.storageBlobDataContributor)
  scope: storage
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

// ---------------------------------------------------------------- Data Factory
resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: '${prefix}-adf-${take(suffix, 6)}'
  location: location
  identity: { type: 'SystemAssigned' }
}

resource adfLake 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, adf.id, roles.storageBlobDataContributor)
  scope: storage
  properties: {
    principalId: adf.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

// ---------------------------------------------------------------- Databricks
resource dbw 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: '${prefix}-dbw-${take(suffix, 6)}'
  location: location
  sku: { name: 'premium' }
  properties: {
    managedResourceGroupId: subscriptionResourceId('Microsoft.Resources/resourceGroups', '${resourceGroup().name}-dbw-managed')
  }
}

resource dbwConnector 'Microsoft.Databricks/accessConnectors@2024-05-01' = {
  name: '${prefix}-dbw-connector'
  location: location
  identity: { type: 'SystemAssigned' }
}

resource connectorLake 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, dbwConnector.id, roles.storageBlobDataContributor)
  scope: storage
  properties: {
    principalId: dbwConnector.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

// ADF autentica no Databricks com a própria MSI
resource adfDatabricks 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dbw.id, adf.id, roles.contributor)
  scope: dbw
  properties: {
    principalId: adf.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
  }
}

// ---------------------------------------------------------------- API
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${take(suffix, 6)}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: toLower('${prefix}acr${take(suffix, 8)}')
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-api-identity'
  location: location
}

resource apiAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, apiIdentity.id, roles.acrPull)
  scope: acr
  properties: {
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-cae-${take(suffix, 6)}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var usaAcr = startsWith(apiImage, acr.properties.loginServer)

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  dependsOn: [apiAcrPull]
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: usaAcr ? [
        { server: acr.properties.loginServer, identity: apiIdentity.id }
      ] : []
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          probes: usaAcr ? [
            { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 30 }
            { type: 'Readiness', httpGet: { path: '/health', port: 8000 }, initialDelaySeconds: 10 }
          ] : []
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '30' } } }
        ]
      }
    }
  }
}

output storageAccount string = storage.name
output lakeRoot string = 'abfss://lakehouse@${storage.name}.dfs.core.windows.net'
output dataFactory string = adf.name
output databricksUrl string = 'https://${dbw.properties.workspaceUrl}'
output databricksWorkspace string = dbw.name
output accessConnectorId string = dbwConnector.id
output dataFactoryPrincipalId string = adf.identity.principalId
output acrLoginServer string = acr.properties.loginServer
output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
