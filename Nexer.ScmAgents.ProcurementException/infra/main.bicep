// =============================================================================
// Nexer SCM Procurement Platform — Procurement Agent
// Main deployment template (resource group scope)
//
// Provisions:
//   - Storage account        (Functions runtime + Durable Functions task hub)
//   - Log Analytics + App Insights
//   - Key Vault              (secrets and sensitive runtime configuration)
//   - App Configuration      (active prompt package references)
//   - Function App           (Flex Consumption, Python — API + Durable approval)
//   - Azure AI Foundry       (optional — can reuse an existing Foundry project)
//   - Static Web App         (React buyer UI, linked to the Function App)
//
// Deploy:
//   az deployment group create \
//     --resource-group rg-scmagents-dev \
//     --template-file infra/main.bicep \
//     --parameters infra/main.parameters.dev.json
// =============================================================================

@description('Short name prefix used in all resource names (lowercase, no spaces).')
@minLength(3)
@maxLength(12)
param namePrefix string = 'scmagents'

@description('Environment name used in resource names (dev, test, prod).')
@allowed(['dev', 'test', 'prod'])
param environmentName string = 'dev'

@description('Azure region for all resources except the Static Web App.')
param location string = resourceGroup().location

@description('Azure region for the Static Web App (limited region availability).')
param staticWebAppLocation string = 'westeurope'

@description('Reuse an existing Azure AI Foundry project instead of provisioning one.')
param useExistingFoundry bool = false

@description('Project endpoint of the existing Foundry project (when useExistingFoundry = true).')
param existingFoundryProjectEndpoint string = ''

@description('Model deployment name the agents use.')
param foundryModelName string = 'gpt-4o'

@description('Model version for the Foundry model deployment.')
param foundryModelVersion string = '2024-11-20'

@description('Tokens-per-minute capacity (in thousands) for the model deployment.')
param foundryModelCapacity int = 50

@description('Link the Function App as the Static Web App backend (requires SWA Standard).')
param linkStaticWebAppBackend bool = true

// ----------------------------------------------------------------------------
// Naming
// ----------------------------------------------------------------------------
var suffix = '${namePrefix}-${environmentName}'
var storageAccountName = take('st${replace(namePrefix, '-', '')}${environmentName}${uniqueString(resourceGroup().id)}', 24)
var functionAppName = 'func-${suffix}'
var appServicePlanName = 'plan-${suffix}'
var logAnalyticsName = 'log-${suffix}'
var appInsightsName = 'appi-${suffix}'
var staticWebAppName = 'stapp-${suffix}'
var foundryAccountName = 'aif-${suffix}'
var foundryProjectName = 'proj-${suffix}'
var keyVaultName = take('kv-${replace(namePrefix, '-', '')}-${environmentName}-${uniqueString(resourceGroup().id)}', 24)
var appConfigurationName = take('appcs-${replace(namePrefix, '-', '')}-${environmentName}-${uniqueString(resourceGroup().id)}', 50)
var d365ClientSecretUri = '${keyVault.outputs.keyVaultUri}secrets/d365-client-secret'

// Foundry project endpoint: existing one, or the deterministic endpoint of the
// account provisioned by the ai-foundry module.
var foundryProjectEndpoint = useExistingFoundry
  ? existingFoundryProjectEndpoint
  : 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'

// ----------------------------------------------------------------------------
// Modules
// ----------------------------------------------------------------------------
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    logAnalyticsName: logAnalyticsName
    appInsightsName: appInsightsName
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    storageAccountName: storageAccountName
  }
}

module keyVault 'modules/key-vault.bicep' = {
  name: 'key-vault'
  params: {
    location: location
    keyVaultName: keyVaultName
    foundryProjectEndpoint: foundryProjectEndpoint
  }
}

module appConfiguration 'modules/app-configuration.bicep' = {
  name: 'app-configuration'
  params: {
    location: location
    appConfigurationName: appConfigurationName
  }
}

module functionApp 'modules/function-app.bicep' = {
  name: 'function-app'
  params: {
    location: location
    functionAppName: functionAppName
    appServicePlanName: appServicePlanName
    storageAccountName: storage.outputs.storageAccountName
    deploymentContainerName: storage.outputs.deploymentContainerName
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    foundryProjectEndpointSecretUri: keyVault.outputs.foundryProjectEndpointSecretUri
    foundryModelName: foundryModelName
    appConfigurationEndpoint: appConfiguration.outputs.appConfigurationEndpoint
    environmentName: environmentName
    d365ClientSecretUri: d365ClientSecretUri
  }
}

resource appConfigurationStore 'Microsoft.AppConfiguration/configurationStores@2023-03-01' existing = {
  name: appConfigurationName
}

resource keyVaultStore 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// --- Configuration access for the Function App managed identity -------------
// App Configuration Data Reader
resource appConfigurationDataReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '516239f1-63e1-4d78-a4de-a74fb236a071'
}

resource appConfigurationDataReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appConfigurationStore.id, functionAppName, appConfigurationDataReaderRole.id)
  scope: appConfigurationStore
  properties: {
    principalId: functionApp.outputs.functionAppPrincipalId
    roleDefinitionId: appConfigurationDataReaderRole.id
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Secrets User
resource keyVaultSecretsUserRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '4633458b-17de-408a-b874-0445c86b69e6'
}

resource keyVaultSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultStore.id, functionAppName, keyVaultSecretsUserRole.id)
  scope: keyVaultStore
  properties: {
    principalId: functionApp.outputs.functionAppPrincipalId
    roleDefinitionId: keyVaultSecretsUserRole.id
    principalType: 'ServicePrincipal'
  }
}

module aiFoundry 'modules/ai-foundry.bicep' = if (!useExistingFoundry) {
  name: 'ai-foundry'
  params: {
    location: location
    foundryAccountName: foundryAccountName
    foundryProjectName: foundryProjectName
    modelName: foundryModelName
    modelVersion: foundryModelVersion
    modelCapacity: foundryModelCapacity
    functionAppPrincipalId: functionApp.outputs.functionAppPrincipalId
  }
}

module staticWebApp 'modules/static-web-app.bicep' = {
  name: 'static-web-app'
  params: {
    location: staticWebAppLocation
    staticWebAppName: staticWebAppName
    functionAppResourceId: functionApp.outputs.functionAppResourceId
    functionAppRegion: location
    linkBackend: linkStaticWebAppBackend
  }
}

// ----------------------------------------------------------------------------
// Outputs (consumed by the CD pipeline and the deployment guide)
// ----------------------------------------------------------------------------
output functionAppName string = functionApp.outputs.functionAppName
output functionAppHostName string = functionApp.outputs.functionAppHostName
output functionAppPrincipalId string = functionApp.outputs.functionAppPrincipalId
output staticWebAppName string = staticWebApp.outputs.staticWebAppName
output staticWebAppHostName string = staticWebApp.outputs.staticWebAppHostName
output storageAccountName string = storage.outputs.storageAccountName
output appInsightsName string = appInsightsName
output foundryProjectEndpoint string = foundryProjectEndpoint
output keyVaultName string = keyVault.outputs.keyVaultName
output appConfigurationName string = appConfiguration.outputs.appConfigurationName
output appConfigurationEndpoint string = appConfiguration.outputs.appConfigurationEndpoint
