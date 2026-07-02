// Azure App Configuration stores dynamic, non-secret runtime configuration.
//
// Prompt package active-version keys are managed with labels per environment
// or tenant. Example key:
//   promptRegistry:scm-procurement-exception-agent:activeVersion
//   label: dev
//
// Prompt package content can also be managed in App Configuration:
//   promptRegistry:<agent_id>:<version>:package
//   promptRegistry:<agent_id>:<version>:prompt:<prompt_type>
//
// Example:
//   promptRegistry:scm-buyer-chat-agent:1.0.0:package
//   promptRegistry:scm-buyer-chat-agent:1.0.0:prompt:system
//   promptRegistry:scm-buyer-chat-agent:1.0.0:prompt:rules

param location string
param appConfigurationName string

resource appConfiguration 'Microsoft.AppConfiguration/configurationStores@2023-03-01' = {
  name: appConfigurationName
  location: location
  sku: {
    name: 'standard'
  }
  properties: {
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

output appConfigurationName string = appConfiguration.name
output appConfigurationResourceId string = appConfiguration.id
output appConfigurationEndpoint string = appConfiguration.properties.endpoint
