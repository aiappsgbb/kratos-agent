@description('Name of the Microsoft Foundry resource')
param name string

@description('Location')
param location string

@description('Tags')
param tags object = {}

@description('Name of the Foundry project')
param projectName string = '${name}-proj'

@description('Name of the GPT model deployment')
param modelDeploymentName string = 'gpt-54'

@description('Model name to deploy')
param modelName string = 'gpt-5.4'

@description('Model version')
param modelVersion string = '2026-03-05'

@description('Deployment SKU capacity (thousands of tokens per minute)')
param modelCapacity int = 350

@description('Application Insights resource ID to connect to the project (powers the Foundry Traces tab). Empty = no connection.')
param appInsightsId string = ''

@description('Application Insights connection string used as the connection credential.')
@secure()
param appInsightsConnectionString string = ''

resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: aiFoundry
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// Connect Application Insights to the project so the Foundry portal Traces tab
// has a data source AND the platform injects the trace connection string into
// hosted agents (their OpenTelemetry gen_ai spans land here).
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (!empty(appInsightsId)) {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsightsId
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appInsightsConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsightsId
    }
  }
}

output id string = aiFoundry.id
output name string = aiFoundry.name
output endpoint string = aiFoundry.properties.endpoint
output modelDeploymentName string = modelDeployment.name
output projectName string = project.name
output projectEndpoint string = '${aiFoundry.properties.endpoint}api/projects/${project.name}'
output projectId string = project.id
output principalId string = aiFoundry.identity.principalId
// The project MI is what pulls the hosted-agent container image from ACR
// (per foundry-hosted-agents skill). Account MI ≠ project MI — both are
// system-assigned, both need different roles.
output projectPrincipalId string = project.identity.principalId
