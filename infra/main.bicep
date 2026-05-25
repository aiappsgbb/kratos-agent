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
param aiGatewayName string = ''

@description('Publisher email for the AI Gateway (APIM)')
param apimPublisherEmail string = 'admin@${environmentName}.com'

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
param staticWebAppLocation string = 'westeurope'

// ─── Resource Naming ───
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
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
    name: !empty(vnetName) ? vnetName : '${abbrs.networkVirtualNetworks}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Log Analytics ───
module logAnalytics './modules/log-analytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    name: !empty(logAnalyticsName) ? logAnalyticsName : '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Application Insights ───
module appInsights './modules/app-insights.bicep' = {
  name: 'app-insights'
  scope: rg
  params: {
    name: !empty(appInsightsName) ? appInsightsName : '${abbrs.insightsComponents}${resourceToken}'
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
    name: !empty(keyVaultName) ? keyVaultName : '${abbrs.keyVaultVaults}${resourceToken}'
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
    name: !empty(cosmosDbAccountName) ? cosmosDbAccountName : '${abbrs.documentDBDatabaseAccounts}${resourceToken}'
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
    name: !empty(aiSearchName) ? aiSearchName : '${abbrs.searchSearchServices}${resourceToken}'
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
    name: !empty(aiServicesName) ? aiServicesName : '${abbrs.cognitiveServicesAccounts}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Bing Search ───
module bingSearch './modules/bing-search.bicep' = {
  name: 'bing-search'
  scope: rg
  params: {
    name: !empty(bingSearchName) ? bingSearchName : '${abbrs.bingSearchAccounts}${resourceToken}'
    tags: tags
    keyVaultName: keyVault.outputs.name
  }
}

// ─── Blob Storage (Skills) ───
module blobStorage './modules/blob-storage.bicep' = {
  name: 'blob-storage'
  scope: rg
  params: {
    name: !empty(storageAccountName) ? storageAccountName : '${abbrs.storageAccounts}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Container Registry ───
module containerRegistry './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: !empty(containerRegistryName) ? containerRegistryName : '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
  }
}

// ─── Container Apps Environment ───
module containerAppsEnv './modules/container-apps-env.bicep' = {
  name: 'container-apps-env'
  scope: rg
  params: {
    name: !empty(containerAppsEnvName) ? containerAppsEnvName : '${abbrs.appManagedEnvironments}${resourceToken}'
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
    name: !empty(agentServiceName) ? agentServiceName : '${abbrs.appContainerApps}agent-${resourceToken}'
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

// ─── AI Gateway (API Management) ───
module aiGateway './modules/ai-gateway.bicep' = {
  name: 'ai-gateway'
  scope: rg
  params: {
    name: !empty(aiGatewayName) ? aiGatewayName : '${abbrs.cognitiveServicesAccounts}${resourceToken}-gateway'
    location: location
    tags: tags
    publisherEmail: apimPublisherEmail
    appInsightsId: appInsights.outputs.id
    appInsightsInstrumentationKey: appInsights.outputs.instrumentationKey
  }
}

// ─── Static Web App ───
module staticWebApp './modules/static-web-app.bicep' = {
  name: 'static-web-app'
  scope: rg
  params: {
    name: !empty(staticWebAppName) ? staticWebAppName : '${abbrs.webStaticSites}${resourceToken}'
    location: staticWebAppLocation
    tags: tags
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
output AI_GATEWAY_URL string = aiGateway.outputs.gatewayUrl
output FOUNDRY_ENDPOINT string = aiFoundry.outputs.endpoint
output FOUNDRY_MODEL_DEPLOYMENT string = aiFoundry.outputs.modelDeploymentName
output AZURE_AI_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
output AZURE_BLOB_STORAGE_ENDPOINT string = blobStorage.outputs.endpoint
output AZURE_BLOB_STORAGE_ACCOUNT_NAME string = blobStorage.outputs.name
