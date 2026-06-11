targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@minLength(1)
@maxLength(90)
@description('Name of the resource group to use or create')
param resourceGroupName string = 'rg-${environmentName}'

@minLength(1)
@description('Primary location for all resources')
param location string

param aiDeploymentsLocation string

@description('Id of the user or app to assign application roles')
param principalId string

@description('Principal type of user or app')
param principalType string

@description('Optional. Name of an existing AI Services account within the resource group. If not provided, a new one will be created.')
param aiFoundryResourceName string = ''

@description('Optional. Name of the AI Foundry project. If not provided, a default name will be used.')
param aiFoundryProjectName string = 'ai-project-${environmentName}'

@description('List of model deployments')
param aiProjectDeploymentsJson string = '[]'

@description('List of connections')
param aiProjectConnectionsJson string = '[]'

@secure()
@description('JSON map of connection name to credentials object. Example: {"my-conn":{"key":"secret"}}')
param aiProjectConnectionCredentialsJson string = '{}'

@description('List of resources to create and connect to the AI project')
param aiProjectDependentResourcesJson string = '[]'

var aiProjectDeployments = json(aiProjectDeploymentsJson)
var aiProjectConnections = json(aiProjectConnectionsJson)
var aiProjectConnectionCreds = json(aiProjectConnectionCredentialsJson)
var aiProjectDependentResources = json(aiProjectDependentResourcesJson)

@description('Enable hosted agent deployment')
param enableHostedAgents bool

@description('Enable the capability host for supporting BYO storage of agent conversations.')
param enableCapabilityHost bool

@description('Enable monitoring for the AI project')
param enableMonitoring bool

@description('When true, skip Foundry project/role/connection provisioning and reference the existing project read-only.')
param useExistingAiProject bool = false

@description('Optional. Existing container registry resource ID.')
param existingContainerRegistryResourceId string = ''

@description('Optional. Existing container registry endpoint (login server).')
param existingContainerRegistryEndpoint string = ''

@description('Optional. Name of an existing ACR connection on the Foundry project.')
param existingAcrConnectionName string = ''

@description('Optional. Existing Application Insights connection string.')
param existingApplicationInsightsConnectionString string = ''

@description('Optional. Existing Application Insights resource ID.')
param existingApplicationInsightsResourceId string = ''

@description('Optional. Name of an existing Application Insights connection on the Foundry project.')
param existingAppInsightsConnectionName string = ''

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// Build dependent resources array — ensure ACR is included when hosted agents are enabled
var hasAcr = contains(map(aiProjectDependentResources, r => r.resource), 'registry')
var shouldCreateAcr = enableHostedAgents && !hasAcr && empty(existingContainerRegistryResourceId) && empty(existingAcrConnectionName)
var dependentResources = shouldCreateAcr ? union(aiProjectDependentResources, [
  {
    resource: 'registry'
    connectionName: 'acr-${uniqueString(subscription().id, resourceGroupName, location)}'
  }
]) : aiProjectDependentResources

// ============================================================
// AI Project (vendored from azd-ai-starter-basic)
// ============================================================
module aiProject 'core/ai/ai-project.bicep' = if (!useExistingAiProject) {
  scope: rg
  name: 'ai-project'
  params: {
    tags: tags
    location: aiDeploymentsLocation
    aiFoundryProjectName: aiFoundryProjectName
    principalId: principalId
    principalType: principalType
    existingAiAccountName: aiFoundryResourceName
    deployments: aiProjectDeployments
    connections: aiProjectConnections
    connectionCredentials: aiProjectConnectionCreds
    additionalDependentResources: dependentResources
    enableMonitoring: enableMonitoring
    enableHostedAgents: enableHostedAgents
    enableCapabilityHost: enableCapabilityHost
    existingContainerRegistryResourceId: existingContainerRegistryResourceId
    existingContainerRegistryEndpoint: existingContainerRegistryEndpoint
    existingAcrConnectionName: existingAcrConnectionName
    existingApplicationInsightsConnectionString: existingApplicationInsightsConnectionString
    existingApplicationInsightsResourceId: existingApplicationInsightsResourceId
    existingAppInsightsConnectionName: existingAppInsightsConnectionName
  }
}

module existingAiProject 'core/ai/existing-ai-project.bicep' = if (useExistingAiProject) {
  scope: rg
  name: 'existing-ai-project'
  params: {
    aiServicesAccountName: aiFoundryResourceName
    aiFoundryProjectName: aiFoundryProjectName
    existingAcrConnectionName: existingAcrConnectionName
    existingContainerRegistryEndpoint: existingContainerRegistryEndpoint
    existingApplicationInsightsConnectionString: existingApplicationInsightsConnectionString
    existingApplicationInsightsResourceId: existingApplicationInsightsResourceId
  }
}

// ============================================================
// Outputs
// ============================================================

// Resources
output AZURE_RESOURCE_GROUP string = resourceGroupName
output AZURE_AI_ACCOUNT_ID string = useExistingAiProject ? existingAiProject.outputs.accountId : aiProject.outputs.accountId
output AZURE_AI_PROJECT_ID string = useExistingAiProject ? existingAiProject.outputs.projectId : aiProject.outputs.projectId
output AZURE_AI_FOUNDRY_PROJECT_ID string = useExistingAiProject ? existingAiProject.outputs.projectId : aiProject.outputs.projectId
output AZURE_AI_ACCOUNT_NAME string = useExistingAiProject ? existingAiProject.outputs.aiServicesAccountName : aiProject.outputs.aiServicesAccountName
output AZURE_AI_PROJECT_NAME string = useExistingAiProject ? existingAiProject.outputs.projectName : aiProject.outputs.projectName

// Endpoints
output AZURE_AI_PROJECT_ENDPOINT string = useExistingAiProject ? existingAiProject.outputs.AZURE_AI_PROJECT_ENDPOINT : aiProject.outputs.AZURE_AI_PROJECT_ENDPOINT
output AZURE_OPENAI_ENDPOINT string = useExistingAiProject ? existingAiProject.outputs.AZURE_OPENAI_ENDPOINT : aiProject.outputs.AZURE_OPENAI_ENDPOINT
output APPLICATIONINSIGHTS_CONNECTION_STRING string = useExistingAiProject ? existingAiProject.outputs.APPLICATIONINSIGHTS_CONNECTION_STRING : aiProject.outputs.APPLICATIONINSIGHTS_CONNECTION_STRING
output APPLICATIONINSIGHTS_RESOURCE_ID string = useExistingAiProject ? existingAiProject.outputs.APPLICATIONINSIGHTS_RESOURCE_ID : aiProject.outputs.APPLICATIONINSIGHTS_RESOURCE_ID

// ACR
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = useExistingAiProject ? existingAiProject.outputs.dependentResources.registry.connectionName : aiProject.outputs.dependentResources.registry.connectionName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = useExistingAiProject ? existingAiProject.outputs.dependentResources.registry.loginServer : aiProject.outputs.dependentResources.registry.loginServer
