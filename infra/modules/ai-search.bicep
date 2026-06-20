@description('Name of the AI Search service')
param name string

@description('Location')
param location string

@description('Tags')
param tags object = {}

@description('Subnet ID for private endpoint')
param subnetId string

@description('VNet ID for DNS zone link')
param vnetId string

@description('''Public network access for the AI Search service.
Defaults to 'enabled' for the same reason as Cosmos: Foundry hosted agents run
in a Microsoft-managed network outside the customer VNet and cannot reach the
private endpoint, so the rag-search skill (which connects to the Search data
plane with DefaultAzureCredential) fails at the network layer when this is
'disabled'. Access stays gated by Microsoft Entra ID RBAC via the role
assignments. Set to 'disabled' only with VNet injection / a managed private
endpoint in front of the agent.''')
@allowed([
  'enabled'
  'disabled'
])
param publicNetworkAccess string = 'enabled'

resource aiSearch 'Microsoft.Search/searchServices@2023-11-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: publicNetworkAccess
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = {
  name: '${name}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${name}-plsc'
        properties: {
          privateLinkServiceId: aiSearch.id
          groupIds: ['searchService']
        }
      }
    ]
  }
}

// Private DNS Zone for AI Search
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.search.windows.net'
  location: 'global'
  tags: tags
}

resource dnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: '${name}-vnet-link'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnetId
    }
    registrationEnabled: false
  }
}

resource dnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'search-dns'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

output id string = aiSearch.id
output name string = aiSearch.name
output endpoint string = 'https://${aiSearch.name}.search.windows.net'
