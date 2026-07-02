// Python Function App on the Flex Consumption plan.
//
// Hosts the platform API (HTTP triggers) and the Durable Functions
// approval lifecycle (orchestrator + activities, task hub: ScmAgentsHub).
//
// Identity-based storage access: the app's system-assigned identity is granted
// blob/queue/table data roles on the storage account, so no storage secrets
// are stored in app settings.

param location string
param functionAppName string
param appServicePlanName string
param storageAccountName string
param deploymentContainerName string
param appInsightsConnectionString string
param foundryProjectEndpointSecretUri string
param foundryModelName string
param appConfigurationEndpoint string
param environmentName string
param d365ClientSecretUri string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: location
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageAccount.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'SystemAssignedIdentity'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 100
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storageAccount.name
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'FOUNDRY_PROJECT_ENDPOINT'
          value: '@Microsoft.KeyVault(SecretUri=${foundryProjectEndpointSecretUri})'
        }
        {
          name: 'FOUNDRY_MODEL'
          value: foundryModelName
        }
        {
          name: 'AZURE_APPCONFIG_ENDPOINT'
          value: appConfigurationEndpoint
        }
        {
          name: 'APP_ENVIRONMENT'
          value: environmentName
        }
        {
          name: 'D365_CLIENT_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${d365ClientSecretUri})'
        }
      ]
    }
  }
}

// --- Storage data-plane roles for the Functions host + Durable task hub -----
// Storage Blob Data Owner (host + deployment container)
resource blobDataOwnerRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
}

// Storage Queue Data Contributor (Durable Functions work-item queues)
resource queueDataContributorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
}

// Storage Table Data Contributor (Durable Functions history/instance tables)
resource tableDataContributorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

resource blobRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, blobDataOwnerRole.id)
  scope: storageAccount
  properties: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: blobDataOwnerRole.id
    principalType: 'ServicePrincipal'
  }
}

resource queueRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, queueDataContributorRole.id)
  scope: storageAccount
  properties: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: queueDataContributorRole.id
    principalType: 'ServicePrincipal'
  }
}

resource tableRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, tableDataContributorRole.id)
  scope: storageAccount
  properties: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: tableDataContributorRole.id
    principalType: 'ServicePrincipal'
  }
}

output functionAppName string = functionApp.name
output functionAppHostName string = functionApp.properties.defaultHostName
output functionAppResourceId string = functionApp.id
output functionAppPrincipalId string = functionApp.identity.principalId
