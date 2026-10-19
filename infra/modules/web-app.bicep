/*
  Container App that runs the Next.js frontend (src/frontend, standalone server).

  It replaced the Static Web App so the UI can host the CopilotKit runtime route
  (/copilotkit/kratos) that relays AG-UI runs to the agent service, and serve
  config.json from environment variables instead of a deploy-time file.
*/

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

@description('Agent service URL: the CopilotKit runtime relays AG-UI runs here, and the browser calls its REST API')
param agentServiceUrl string

@description('OBO sign-in: SPA client app id (empty disables OBO sign-in in the UI)')
param oboClientAppClientId string = ''

@description('OBO sign-in: tenant id')
param oboTenantId string = ''

@description('OBO sign-in: identifier URI of the OBO server app')
param oboServerAppIdentifierUri string = ''

@description('OBO sign-in: delegated scope value on the OBO server app')
param oboServerAppScopeValue string = 'access_as_user'

@description('OBO MCP server name the user token is keyed by')
param oboMcpServerName string = 'graph-obo'

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var acrName = replace(containerRegistryName, '-', '')

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

// User-assigned identity so AcrPull exists before the app validates its registry.
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

resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  dependsOn: [acrPullRole]
  identity: {
    type: 'UserAssigned'
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
        targetPort: 3000
        transport: 'http'
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AGENT_BACKEND_URL', value: agentServiceUrl }
            // config.json prefers the image's basePath (same-origin behind Front Door).
            { name: 'KRATOS_API_URL', value: agentServiceUrl }
            { name: 'OBO_CLIENT_APP_CLIENT_ID', value: oboClientAppClientId }
            { name: 'OBO_TENANT_ID', value: oboTenantId }
            { name: 'OBO_SERVER_APP_IDENTIFIER_URI', value: oboServerAppIdentifierUri }
            { name: 'OBO_SERVER_APP_SCOPE_VALUE', value: oboServerAppScopeValue }
            { name: 'OBO_MCP_SERVER_NAME', value: oboMcpServerName }
            { name: 'COPILOTKIT_TELEMETRY_DISABLED', value: 'true' }
            { name: 'NEXT_TELEMETRY_DISABLED', value: '1' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
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

output id string = webApp.id
output name string = webApp.name
output url string = 'https://${webApp.properties.configuration.ingress.fqdn}'
