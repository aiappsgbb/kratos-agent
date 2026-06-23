targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (used for resource naming)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Principal ID of the deploying user for role assignments')
param principalId string = ''

// Optional overrides
param containerAppsEnvName string = ''
param containerRegistryName string = ''
param cosmosDbAccountName string = ''
param aiSearchName string = ''
param aiServicesName string = ''
param bingSearchName string = ''
param keyVaultName string = ''
param appInsightsName string = ''
param logAnalyticsName string = ''
param staticWebAppName string = ''
param agentServiceName string = ''
param vnetName string = ''
param storageAccountName string = ''

@description('Optional prefix prepended to generated resource names. Empty (default) yields names identical to the base template, so the canonical/prod deployment is unaffected. Set per-subscription (e.g. via AZURE_RESOURCE_PREFIX) to avoid cross-subscription resource name collisions.')
param resourcePrefix string = ''

@description('Path prefix for the agent API on the gateway (set during Foundry portal registration)')
param agentApiPath string = 'kratos-agent'

@description('Location for the Static Web App (must be one of: centralus, eastus2, westus2, westeurope, eastasia)')
@allowed([
  'centralus'
  'eastus2'
  'westus2'
  'westeurope'
  'eastasia'
])
param staticWebAppLocation string = 'eastus2'

// ─── Resource Naming ───
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var namePrefix = empty(resourcePrefix) ? '' : '${resourcePrefix}-'
var namePrefixNoHyphen = empty(resourcePrefix) ? '' : toLower(resourcePrefix)
var tags = { 'azd-env-name': environmentName, project: 'kratos-agent' }

// ─── Resource Group ───
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// ─── Networking ───
module network './modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: {
    name: !empty(vnetName) ? vnetName : '${namePrefix}${abbrs.networkVirtualNetworks}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Log Analytics ───
module logAnalytics './modules/log-analytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    name: !empty(logAnalyticsName) ? logAnalyticsName : '${namePrefix}${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Application Insights ───
module appInsights './modules/app-insights.bicep' = {
  name: 'app-insights'
  scope: rg
  params: {
    name: !empty(appInsightsName) ? appInsightsName : '${namePrefix}${abbrs.insightsComponents}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
  }
}

// ─── Key Vault ───
module keyVault './modules/key-vault.bicep' = {
  name: 'key-vault'
  scope: rg
  params: {
    name: !empty(keyVaultName) ? keyVaultName : '${namePrefix}${abbrs.keyVaultVaults}${resourceToken}'
    location: location
    tags: tags
    principalId: principalId
    subnetId: network.outputs.privateEndpointSubnetId
    vnetId: network.outputs.id
  }
}

// ─── Cosmos DB ───
module cosmosDb './modules/cosmos-db.bicep' = {
  name: 'cosmos-db'
  scope: rg
  params: {
    name: !empty(cosmosDbAccountName) ? cosmosDbAccountName : '${namePrefix}${abbrs.documentDBDatabaseAccounts}${resourceToken}'
    location: location
    tags: tags
    subnetId: network.outputs.privateEndpointSubnetId
    vnetId: network.outputs.id
    keyVaultName: keyVault.outputs.name
  }
}

// ─── AI Search ───
module aiSearch './modules/ai-search.bicep' = {
  name: 'ai-search'
  scope: rg
  params: {
    name: !empty(aiSearchName) ? aiSearchName : '${namePrefix}${abbrs.searchSearchServices}${resourceToken}'
    location: location
    tags: tags
    subnetId: network.outputs.privateEndpointSubnetId
    vnetId: network.outputs.id
  }
}

// ─── Microsoft Foundry ───
module aiFoundry './modules/ai-services.bicep' = {
  name: 'ai-foundry'
  scope: rg
  params: {
    name: !empty(aiServicesName) ? aiServicesName : '${namePrefix}${abbrs.cognitiveServicesAccounts}${resourceToken}'
    location: location
    tags: tags
    appInsightsId: appInsights.outputs.id
    appInsightsConnectionString: appInsights.outputs.connectionString
  }
}

// ─── Bing Search ───
module bingSearch './modules/bing-search.bicep' = {
  name: 'bing-search'
  scope: rg
  params: {
    name: !empty(bingSearchName) ? bingSearchName : '${namePrefix}${abbrs.bingSearchAccounts}${resourceToken}'
    tags: tags
    keyVaultName: keyVault.outputs.name
  }
}

// ─── Blob Storage (Skills) ───
module blobStorage './modules/blob-storage.bicep' = {
  name: 'blob-storage'
  scope: rg
  params: {
    name: !empty(storageAccountName) ? storageAccountName : '${namePrefixNoHyphen}${abbrs.storageAccounts}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Container Registry ───
module containerRegistry './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: !empty(containerRegistryName) ? containerRegistryName : '${namePrefixNoHyphen}${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Container Apps Environment ───
module containerAppsEnv './modules/container-apps-env.bicep' = {
  name: 'container-apps-env'
  scope: rg
  params: {
    name: !empty(containerAppsEnvName) ? containerAppsEnvName : '${namePrefix}${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
    subnetId: network.outputs.containerAppsSubnetId
  }
}

// ─── Agent Service (Container App) ───
module agentService './modules/agent-service.bicep' = {
  name: 'agent-service'
  scope: rg
  params: {
    name: !empty(agentServiceName) ? agentServiceName : '${namePrefix}${abbrs.appContainerApps}agent-${resourceToken}'
    location: location
    tags: tags
    containerAppsEnvId: containerAppsEnv.outputs.id
    containerRegistryName: containerRegistry.outputs.name
    appInsightsConnectionString: appInsights.outputs.connectionString
    appInsightsResourceId: appInsights.outputs.id
    cosmosDbEndpoint: cosmosDb.outputs.endpoint
    aiSearchEndpoint: aiSearch.outputs.endpoint
    keyVaultUri: keyVault.outputs.uri
    foundryEndpoint: aiFoundry.outputs.endpoint
    foundryModelDeployment: aiFoundry.outputs.modelDeploymentName
    foundryProjectName: aiFoundry.outputs.projectName
    foundryProjectEndpoint: aiFoundry.outputs.projectEndpoint
    bingSearchEndpoint: bingSearch.outputs.endpoint
    blobStorageEndpoint: blobStorage.outputs.endpoint
    staticWebAppUrl: staticWebApp.outputs.url
  }
}

// ─── Static Web App ───
module staticWebApp './modules/static-web-app.bicep' = {
  name: 'static-web-app'
  scope: rg
  params: {
    name: !empty(staticWebAppName) ? staticWebAppName : '${namePrefix}${abbrs.webStaticSites}${resourceToken}'
    location: staticWebAppLocation
    tags: tags
  }
}

// ─── OBO MCP Server: identity, Entra apps, container app ───
// One user-assigned managed identity is the ACR-pull identity, the container
// runtime identity, AND the federated subject the OBO server app trusts.
module oboIdentity './modules/obo-identity.bicep' = {
  name: 'obo-identity'
  scope: rg
  params: {
    name: 'id-obo-${resourceToken}'
    location: location
    tags: tags
  }
}

// SPA client app (MSAL.js signs the user in here). Deployed first so its appId
// can pre-authorize the server app, avoiding a circular dependency.
module oboEntraAppClient './modules/obo-entra-app.bicep' = {
  name: 'obo-entra-app-client'
  scope: rg
  params: {
    entraAppDisplayName: 'kratos-obo-client-${environmentName}'
    entraAppUniqueName: 'kratos-obo-client-${resourceToken}'
    isServer: false
    spaRedirectUris: [
      staticWebApp.outputs.url
      'http://localhost:3000'
      'http://localhost:5173'
      'http://localhost:4280'
    ]
  }
}

// OBO server app (the MCP server's Entra identity + Graph User.Read + FIC).
module oboEntraAppServer './modules/obo-entra-app.bicep' = {
  name: 'obo-entra-app-server'
  scope: rg
  params: {
    entraAppDisplayName: 'kratos-obo-server-${environmentName}'
    entraAppUniqueName: 'kratos-obo-server-${resourceToken}'
    isServer: true
    knownClientAppId: oboEntraAppClient.outputs.entraAppClientId
    acaManagedIdentityObjectId: oboIdentity.outputs.principalId
  }
}

module oboMcpServer './modules/obo-mcp-server.bicep' = {
  name: 'obo-mcp-server'
  scope: rg
  params: {
    name: '${namePrefix}${abbrs.appContainerApps}obo-${resourceToken}'
    location: location
    tags: tags
    containerAppsEnvId: containerAppsEnv.outputs.id
    containerRegistryName: containerRegistry.outputs.name
    appInsightsConnectionString: appInsights.outputs.connectionString
    oboIdentityId: oboIdentity.outputs.id
    oboIdentityClientId: oboIdentity.outputs.clientId
    oboIdentityPrincipalId: oboIdentity.outputs.principalId
    tenantId: tenant().tenantId
    oboApiClientId: oboEntraAppServer.outputs.entraAppClientId
    allowedClientAppIds: oboEntraAppClient.outputs.entraAppClientId
  }
}

// ─── Role Assignments ───
module roleAssignments './modules/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  params: {
    agentServicePrincipalId: agentService.outputs.principalId
    cosmosDbAccountName: cosmosDb.outputs.name
    aiSearchName: aiSearch.outputs.name
    aiServicesName: aiFoundry.outputs.name
    aiServicesPrincipalId: aiFoundry.outputs.principalId
    aiServicesProjectPrincipalId: aiFoundry.outputs.projectPrincipalId
    keyVaultName: keyVault.outputs.name
    storageAccountName: blobStorage.outputs.name
    appInsightsName: appInsights.outputs.name
    containerRegistryName: containerRegistry.outputs.name
    principalId: principalId
  }
}

// ─── Outputs ───
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_APPS_ENV_NAME string = containerAppsEnv.outputs.name
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.outputs.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AZURE_COSMOS_DB_ENDPOINT string = cosmosDb.outputs.endpoint
output AZURE_AI_SEARCH_ENDPOINT string = aiSearch.outputs.endpoint
output AZURE_KEY_VAULT_URI string = keyVault.outputs.uri
output AZURE_APP_INSIGHTS_CONNECTION_STRING string = appInsights.outputs.connectionString
output AZURE_STATIC_WEB_APP_URL string = staticWebApp.outputs.url
output AGENT_SERVICE_DIRECT_URL string = agentService.outputs.url
output AGENT_SERVICE_URL string = agentService.outputs.url
output FOUNDRY_ENDPOINT string = aiFoundry.outputs.endpoint
output FOUNDRY_MODEL_DEPLOYMENT string = aiFoundry.outputs.modelDeploymentName
output AZURE_AI_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
// Full ARM resource ID of the Foundry project. Surfacing it as an azd output
// writes AZURE_AI_PROJECT_ID into the environment during `azd provision`, so the
// `azure.ai.agent` extension can deploy the hosted agent without a manual
// `azd env set AZURE_AI_PROJECT_ID ...` step. Also consumed by
// hooks/assign-agent-roles.sh to resolve the agent identity.
output AZURE_AI_PROJECT_ID string = aiFoundry.outputs.projectId
output AZURE_BLOB_STORAGE_ENDPOINT string = blobStorage.outputs.endpoint
output AZURE_BLOB_STORAGE_ACCOUNT_NAME string = blobStorage.outputs.name

// ─── OBO MCP server outputs ───
output OBO_MCP_SERVER_URL string = oboMcpServer.outputs.url
output OBO_MCP_SERVER_MCP_URL string = oboMcpServer.outputs.mcpUrl
output OBO_SERVER_APP_CLIENT_ID string = oboEntraAppServer.outputs.entraAppClientId
output OBO_SERVER_APP_IDENTIFIER_URI string = oboEntraAppServer.outputs.entraAppIdentifierUri
output OBO_SERVER_APP_SCOPE_VALUE string = oboEntraAppServer.outputs.entraAppScopeValue
output OBO_CLIENT_APP_CLIENT_ID string = oboEntraAppClient.outputs.entraAppClientId
output OBO_TENANT_ID string = tenant().tenantId
