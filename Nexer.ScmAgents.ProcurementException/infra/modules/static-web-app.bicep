// Static Web App hosting the React buyer UI.
//
// Standard tier so the Function App can be linked as the SWA backend:
// the UI calls relative /api/* paths and SWA proxies them to the Function
// App — no CORS configuration and no frontend code changes required.

param location string
param staticWebAppName string
param functionAppResourceId string
param functionAppRegion string
param linkBackend bool

resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
    provider: 'DevOps'
  }
}

resource linkedBackend 'Microsoft.Web/staticSites/linkedBackends@2024-04-01' = if (linkBackend) {
  parent: staticWebApp
  name: 'procurement-api'
  properties: {
    backendResourceId: functionAppResourceId
    region: functionAppRegion
  }
}

output staticWebAppName string = staticWebApp.name
output staticWebAppHostName string = staticWebApp.properties.defaultHostname
