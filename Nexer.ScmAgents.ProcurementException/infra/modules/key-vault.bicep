// Key Vault for sensitive runtime configuration.
//
// App settings reference secrets by URI so values are not stored directly on
// the Function App. The Function App managed identity is granted access from
// the main template.

param location string
param keyVaultName string
param foundryProjectEndpoint string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource foundryProjectEndpointSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'foundry-project-endpoint'
  properties: {
    value: foundryProjectEndpoint
  }
}

output keyVaultName string = keyVault.name
output keyVaultResourceId string = keyVault.id
output keyVaultUri string = keyVault.properties.vaultUri
output foundryProjectEndpointSecretUri string = foundryProjectEndpointSecret.properties.secretUri
