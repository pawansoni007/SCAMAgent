// Azure AI Foundry account + project + model deployment.
//
// The agents (Microsoft Agent Framework + FoundryChatClient) authenticate to
// the project endpoint with the Function App's system-assigned managed
// identity, which is granted the "Azure AI User" role on the account.

param location string
param foundryAccountName string
param foundryProjectName string
param modelName string
param modelVersion string
param modelCapacity int
param functionAppPrincipalId string

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: foundryAccountName
  location: location
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'S0'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryAccountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: foundryAccount
  name: foundryProjectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'SCM Agents — Procurement'
    description: 'Procurement Agent platform: orchestrator, exception agent and buyer chat agent.'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: foundryAccount
  name: modelName
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [
    foundryProject
  ]
}

// Azure AI User — allows the Function App identity to call the project
// endpoint (chat completions / agent runs).
resource azureAiUserRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  scope: subscription()
  name: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
}

resource functionAppAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, functionAppPrincipalId, azureAiUserRole.id)
  scope: foundryAccount
  properties: {
    principalId: functionAppPrincipalId
    roleDefinitionId: azureAiUserRole.id
    principalType: 'ServicePrincipal'
  }
}

output foundryAccountName string = foundryAccount.name
output foundryProjectEndpoint string = 'https://${foundryAccount.name}.services.ai.azure.com/api/projects/${foundryProject.name}'
output modelDeploymentName string = modelDeployment.name
