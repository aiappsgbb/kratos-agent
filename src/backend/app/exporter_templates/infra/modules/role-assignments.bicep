// Role Assignments — trimmed for Kratos Hosted-Agent export.
//
// This is a fork of Kratos's repo-root infra/modules/role-assignments.bicep
// with the `agentServicePrincipalId` parameter dropped. In the exported
// project there is NO Container App backend — the Foundry hosted-agent's
// system-assigned MI is the single principal for all data-plane access.

@description('Cosmos DB account name')
param cosmosDbAccountName string

@description('AI Search service name')
param aiSearchName string

@description('Microsoft Foundry resource name')
param aiServicesName string

@description('Microsoft Foundry system-assigned principal ID (compile-time output from the ai-services module)')
param aiServicesPrincipalId string

@description('Microsoft Foundry PROJECT system-assigned principal ID. Per foundry-hosted-agents skill, this is the MI that actually pulls the hosted-agent container image from ACR — granting AcrPull only to the account MI is insufficient and causes ImageError at first invoke.')
param aiServicesProjectPrincipalId string = ''

@description('Key Vault name')
param keyVaultName string

@description('Storage Account name for skills blob storage')
param storageAccountName string

@description('Application Insights resource name (for Monitoring Reader RBAC)')
param appInsightsName string = ''

@description('Container Registry name (for AcrPull grant to the Foundry hosted-agent MI)')
param containerRegistryName string = ''

@description('Deploying user principal ID')
param principalId string = ''

// ─── Built-in Role Definition IDs ───
var cosmosDbDataContributor = '00000000-0000-0000-0000-000000000002'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var cognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var monitoringReader = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

// ─── References ───
resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2024-02-15-preview' existing = {
  name: cosmosDbAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource aiSearch 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: aiSearchName
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServicesName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(appInsightsName)) {
  name: appInsightsName
}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (!empty(containerRegistryName)) {
  name: containerRegistryName
}

// ─── Foundry Hosted Agent → Cosmos DB ───
resource agentCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-02-15-preview' = {
  parent: cosmosDb
  name: guid(cosmosDb.id, aiServicesPrincipalId, cosmosDbDataContributor)
  properties: {
    roleDefinitionId: '${cosmosDb.id}/sqlRoleDefinitions/${cosmosDbDataContributor}'
    principalId: aiServicesPrincipalId
    scope: cosmosDb.id
  }
}

// ─── Foundry Hosted Agent → Key Vault ───
resource agentKeyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, aiServicesPrincipalId, keyVaultSecretsUser)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → AI Search (Reader) ───
resource agentSearchRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiSearch.id, aiServicesPrincipalId, searchIndexDataReader)
  scope: aiSearch
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → AI Search (Contributor — for ingestion) ───
resource agentSearchContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiSearch.id, aiServicesPrincipalId, searchIndexDataContributor)
  scope: aiSearch
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → Microsoft Foundry (OpenAI User) ───
resource agentAiServicesRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, aiServicesPrincipalId, cognitiveServicesOpenAIUser)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUser)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → Foundry Agent Service (Cognitive Services User) ───
resource agentCogServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, aiServicesPrincipalId, cognitiveServicesUser)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → Blob Storage (Skills) ───
resource agentStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, aiServicesPrincipalId, storageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → Application Insights (Monitoring Reader) ───
resource agentAppInsightsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(appInsightsName)) {
  name: guid(appInsights.id, aiServicesPrincipalId, monitoringReader)
  scope: appInsights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReader)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Foundry Hosted Agent → ACR (AcrPull, so Foundry can pull the hosted-agent image) ───
resource aiServicesAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(containerRegistryName)) {
  name: guid(containerRegistry.id, aiServicesPrincipalId, acrPull)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: aiServicesPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── AI Services PROJECT MI → ACR (AcrPull) ───
// The Foundry PROJECT MI is what actually pulls the hosted-agent container
// image at first invoke (per foundry-hosted-agents skill). Account MI alone
// is insufficient and produces ImageError. Belt-and-braces with the account
// MI grant above.
resource aiServicesProjectAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(containerRegistryName) && !empty(aiServicesProjectPrincipalId)) {
  name: guid(containerRegistry.id, aiServicesProjectPrincipalId, acrPull)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: aiServicesProjectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Deploying User → Cosmos DB (for local dev) ───
resource userCosmosRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-02-15-preview' = if (!empty(principalId)) {
  parent: cosmosDb
  name: guid(cosmosDb.id, principalId, cosmosDbDataContributor)
  properties: {
    roleDefinitionId: '${cosmosDb.id}/sqlRoleDefinitions/${cosmosDbDataContributor}'
    principalId: principalId
    scope: cosmosDb.id
  }
}

// ─── Deploying User → Key Vault ───
resource userKeyVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(keyVault.id, principalId, keyVaultSecretsUser)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: principalId
    principalType: 'User'
  }
}

// ─── Deploying User → Microsoft Foundry (for local dev) ───
resource userAiServicesRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(aiServices.id, principalId, cognitiveServicesOpenAIUser)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUser)
    principalId: principalId
    principalType: 'User'
  }
}

// ─── Deploying User → Foundry Agent Service (for local dev) ───
resource userCogServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(aiServices.id, principalId, cognitiveServicesUser)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: principalId
    principalType: 'User'
  }
}

// ─── Deploying User → Blob Storage (for local dev) ───
resource userStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(storageAccount.id, principalId, storageBlobDataContributor)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
    principalId: principalId
    principalType: 'User'
  }
}

// ─── Deploying User → AI Search (Contributor — for local data ingestion) ───
resource userSearchContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(aiSearch.id, principalId, searchIndexDataContributor)
  scope: aiSearch
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
    principalId: principalId
    principalType: 'User'
  }
}
