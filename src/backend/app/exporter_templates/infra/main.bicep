// Trimmed Kratos infrastructure for Foundry Hosted Agent export.
//
// This is a fork of Kratos's repo-root infra/main.bicep that drops the
// modules a standalone hosted agent doesn't need:
//   * container-apps-env  — no Container App backend
//   * agent-service       — same
//   * ai-gateway          — no APIM
//   * static-web-app      — no frontend
//   * bing-search         — optional capability, omitted
//
// The Foundry hosted-agent's system-assigned managed identity replaces the
// Container App MI as the principal for all data-plane RBAC (Cosmos / KV /
// AI Search / Blob / Foundry).

targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (used for resource naming)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Principal ID of the deploying user for local-dev role assignments')
param principalId string = ''

// Optional overrides
param containerRegistryName string = ''
param cosmosDbAccountName string = ''
param aiSearchName string = ''
param aiServicesName string = ''
param keyVaultName string = ''
param appInsightsName string = ''
param logAnalyticsName string = ''
param vnetName string = ''
param storageAccountName string = ''

// ─── Resource Naming ───
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName, project: 'kratos-agent-export' }

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

// ─── Role Assignments ───
//
// All data-plane access goes to the Foundry hosted-agent's system-assigned
// MI. No Container App in this layout, so the agentServicePrincipalId
// parameter is gone.
module roleAssignments './modules/role-assignments.bicep' = {
  name: 'role-assignments'
  scope: rg
  params: {
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
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.outputs.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AZURE_COSMOS_DB_ENDPOINT string = cosmosDb.outputs.endpoint
output AZURE_AI_SEARCH_ENDPOINT string = aiSearch.outputs.endpoint
output AZURE_KEY_VAULT_URI string = keyVault.outputs.uri
output AZURE_APP_INSIGHTS_CONNECTION_STRING string = appInsights.outputs.connectionString
output AZURE_AI_ACCOUNT_NAME string = aiFoundry.outputs.name
output FOUNDRY_ENDPOINT string = aiFoundry.outputs.endpoint
output FOUNDRY_MODEL_DEPLOYMENT string = aiFoundry.outputs.modelDeploymentName
output AZURE_AI_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
// Extension contract drift (per foundry-hosted-agents skill): azure.ai.agents
// extension v0.1.31+ reads FOUNDRY_PROJECT_ENDPOINT, older versions read
// AZURE_AI_PROJECT_ENDPOINT. Emit both with the same value until the
// extension settles on one name.
output FOUNDRY_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
output AZURE_AI_PROJECT_ID string = aiFoundry.outputs.projectId
output AZURE_BLOB_STORAGE_ENDPOINT string = blobStorage.outputs.endpoint
output AZURE_BLOB_STORAGE_ACCOUNT_NAME string = blobStorage.outputs.name
