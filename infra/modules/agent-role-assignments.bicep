// ─────────────────────────────────────────────────────────────────────────────
// Least-privilege data-plane roles for Foundry hosted-agent instance identities.
//
// WHY THIS IS A SEPARATE MODULE (and not part of role-assignments.bicep):
// A Foundry hosted agent (`host: azure.ai.agent`) runs under its own managed
// "AgentIdentity" service principal, which is created by `azd ai agent deploy`
// AFTER `azd provision` has already run the main Bicep deployment. A
// `Microsoft.Authorization/roleAssignments` resource requires a principalId that
// already exists, so the agent identity cannot be referenced during provision.
//
// This module declares those role assignments IN BICEP (declarative, idempotent,
// reviewable, what-if-able) and is applied post-deploy by hooks/assign-agent-roles.sh,
// which performs the one thing Bicep cannot — a Microsoft Entra ID lookup of the
// runtime-created agent identity — and passes the resolved principalIds here.
//
// All inputs are deployment-specific and supplied at apply time; nothing about a
// particular environment is baked in.
// ─────────────────────────────────────────────────────────────────────────────

@description('Object IDs of the Foundry hosted-agent instance identities (resolved at deploy time from Microsoft Entra ID).')
param agentPrincipalIds array

@description('Cosmos DB account name')
param cosmosDbAccountName string

@description('AI Search service name')
param aiSearchName string

@description('Microsoft Foundry (AI Services) account name')
param aiServicesName string

@description('Key Vault name')
param keyVaultName string

@description('Storage Account name for skills blob storage')
param storageAccountName string

// ─── Built-in role definition IDs (stable across all tenants) ───
var cognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // model inference
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'       // Foundry agent runtime plane
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'       // read skills from blob (read-only = least privilege)
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'       // RAG query (read-only)
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'         // read skill secrets
var cosmosDbDataContributor = '00000000-0000-0000-0000-000000000002'     // conversation persistence (data plane; no read-only built-in suffices for writes)

// ─── Existing resources ───
resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServicesName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource aiSearch 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: aiSearchName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2024-02-15-preview' existing = {
  name: cosmosDbAccountName
}

// ─── Agent identity → Microsoft Foundry (model inference) ───
resource agentOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pid in agentPrincipalIds: {
  name: guid(aiServices.id, pid, cognitiveServicesOpenAIUser)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUser)
    principalId: pid
    principalType: 'ServicePrincipal'
  }
}]

// ─── Agent identity → Foundry agent runtime plane ───
resource agentCognitiveUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pid in agentPrincipalIds: {
  name: guid(aiServices.id, pid, cognitiveServicesUser)
  scope: aiServices
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: pid
    principalType: 'ServicePrincipal'
  }
}]

// ─── Agent identity → Blob Storage (read skills) ───
resource agentBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pid in agentPrincipalIds: {
  name: guid(storageAccount.id, pid, storageBlobDataReader)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReader)
    principalId: pid
    principalType: 'ServicePrincipal'
  }
}]

// ─── Agent identity → AI Search (RAG read) ───
resource agentSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pid in agentPrincipalIds: {
  name: guid(aiSearch.id, pid, searchIndexDataReader)
  scope: aiSearch
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
    principalId: pid
    principalType: 'ServicePrincipal'
  }
}]

// ─── Agent identity → Key Vault (read skill secrets) ───
resource agentKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pid in agentPrincipalIds: {
  name: guid(keyVault.id, pid, keyVaultSecretsUser)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: pid
    principalType: 'ServicePrincipal'
  }
}]

// ─── Agent identity → Cosmos DB (conversation persistence, data plane) ───
resource agentCosmosData 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-02-15-preview' = [for pid in agentPrincipalIds: {
  parent: cosmosDb
  name: guid(cosmosDb.id, pid, cosmosDbDataContributor)
  properties: {
    roleDefinitionId: '${cosmosDb.id}/sqlRoleDefinitions/${cosmosDbDataContributor}'
    principalId: pid
    scope: cosmosDb.id
  }
}]
