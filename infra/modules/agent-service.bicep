@description('Name of the Container App')
param name string

@description('Location')
param location string

@description('Tags')
param tags object = {}

@description('Container Apps Environment ID')
param containerAppsEnvId string

@description('Container Registry name')
param containerRegistryName string

@description('App Insights connection string')
param appInsightsConnectionString string

@description('App Insights resource ID (for resource-scoped KQL queries from the Traces panel)')
param appInsightsResourceId string = ''

@description('Cosmos DB endpoint')
param cosmosDbEndpoint string

@description('AI Search endpoint')
param aiSearchEndpoint string

@description('Key Vault URI')
param keyVaultUri string

@description('Voice mode flag (opt-in speech-to-speech)')
param voiceEnabled bool = false

@description('gpt-realtime deployment name for voice mode')
param voiceDeployment string = ''

@description('Microsoft Foundry endpoint')
param foundryEndpoint string

@description('Foundry model deployment name')
param foundryModelDeployment string

@description('Bing Search endpoint')
param bingSearchEndpoint string

@description('Foundry project name')
param foundryProjectName string

@description('Foundry project endpoint (e.g. https://host/api/projects/proj)')
param foundryProjectEndpoint string = ''

@description('Hosted agent name deployed in Foundry')
param foundryAgentName string = 'kratos-agent'

@description('Azure Blob Storage endpoint for skills')
param blobStorageEndpoint string

@description('Static Web App URL for CORS (e.g. https://xxx.azurestaticapps.net)')
param staticWebAppUrl string = ''

// ─── ACR pull identity ───
// A User-Assigned Managed Identity is created for ACR access so that the
// AcrPull role assignment exists BEFORE the Container App tries to validate
// the registry config.  The System-Assigned identity is still used for all
// other service-to-service RBAC (Cosmos, Key Vault, AI Search, etc.).

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var acrName = replace(containerRegistryName, '-', '')

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource acrPullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${name}-acr-pull'
  location: location
  tags: tags
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, acrPullIdentity.id, acrPullRoleId)
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: acrPullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Container App ───
resource agentService 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'agent-service' })
  dependsOn: [acrPullRole]
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${acrPullIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvId
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: acrPullIdentity.id
        }
      ]
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        corsPolicy: {
          allowedOrigins: empty(staticWebAppUrl) ? ['*'] : [staticWebAppUrl]
          allowedMethods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
          allowedHeaders: ['*']
          maxAge: 3600
        }
      }
    }
    template: {
      containers: [
        {
          name: 'agent-service'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'APPLICATION_INSIGHTS_RESOURCE_ID', value: appInsightsResourceId }
            { name: 'COSMOS_DB_ENDPOINT', value: cosmosDbEndpoint }
            { name: 'AZURE_AI_SEARCH_ENDPOINT', value: aiSearchEndpoint }
            { name: 'KEY_VAULT_URI', value: keyVaultUri }
            { name: 'FOUNDRY_ENDPOINT', value: foundryEndpoint }
            { name: 'FOUNDRY_MODEL_DEPLOYMENT', value: foundryModelDeployment }
            { name: 'VOICE_ENABLED', value: string(voiceEnabled) }
            { name: 'VOICE_DEPLOYMENT', value: voiceDeployment }
            { name: 'FOUNDRY_PROJECT_NAME', value: foundryProjectName }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'FOUNDRY_AGENT_NAME', value: foundryAgentName }
            { name: 'BING_SEARCH_ENDPOINT', value: bingSearchEndpoint }
            { name: 'BLOB_STORAGE_ENDPOINT', value: blobStorageEndpoint }
            { name: 'OTEL_SERVICE_NAME', value: 'kratos-agent-service' }
            { name: 'AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED', value: 'true' }
            { name: 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT', value: 'true' }
            { name: 'ENVIRONMENT', value: 'production' }
            { name: 'ALLOWED_ORIGINS', value: empty(staticWebAppUrl) ? '*' : staticWebAppUrl }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

output id string = agentService.id
output name string = agentService.name
output url string = 'https://${agentService.properties.configuration.ingress.fqdn}'
output principalId string = agentService.identity.principalId
