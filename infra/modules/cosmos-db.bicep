@description('Name of the Cosmos DB account')
param name string

@description('Location')
param location string

@description('Tags')
param tags object = {}

@description('Subnet ID for private endpoint')
param subnetId string

@description('VNet ID for DNS zone link')
param vnetId string

@description('Key Vault name for storing connection info')
param keyVaultName string

@description('''Public network access for the Cosmos DB account.
Defaults to 'Enabled' because Foundry hosted agents run in a Microsoft-managed
network OUTSIDE the customer VNet and therefore cannot reach the private
endpoint — with 'Disabled' the agent's conversation-persistence calls fail at
the network layer (before RBAC is even evaluated). The data plane stays locked
down: local (key) auth is disabled, so only Microsoft Entra ID identities with
an explicit Cosmos data-plane role can connect. Set to 'Disabled' only if you
front the agent with VNet injection / a managed private endpoint.''')
@allowed([
  'Enabled'
  'Disabled'
])
param publicNetworkAccess string = 'Enabled'

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts@2024-02-15-preview' = {
  name: name
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    publicNetworkAccess: publicNetworkAccess
    disableLocalAuth: true
  }
}

// Database
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-02-15-preview' = {
  parent: cosmosDb
  name: 'kratos-agent'
  properties: {
    resource: {
      id: 'kratos-agent'
    }
  }
}

// Conversations container with userId partition key
resource conversationsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = {
  parent: database
  name: 'conversations'
  properties: {
    resource: {
      id: 'conversations'
      partitionKey: {
        paths: ['/userId']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/*' }
        ]
        excludedPaths: [
          { path: '/"_etag"/?' }
        ]
      }
      defaultTtl: -1
    }
  }
}

// Messages container
resource messagesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = {
  parent: database
  name: 'messages'
  properties: {
    resource: {
      id: 'messages'
      partitionKey: {
        paths: ['/conversationId']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/*' }
        ]
        excludedPaths: [
          { path: '/"_etag"/?' }
        ]
      }
      defaultTtl: -1
    }
  }
}

// Settings container — stores system prompt and other admin config
resource settingsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = {
  parent: database
  name: 'settings'
  properties: {
    resource: {
      id: 'settings'
      partitionKey: {
        paths: ['/category']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/*' }
        ]
        excludedPaths: [
          { path: '/"_etag"/?' }
        ]
      }
      defaultTtl: -1
    }
  }
}

// Sessions container — stores SDK session ID ↔ conversation ID mapping
resource sessionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = {
  parent: database
  name: 'sessions'
  properties: {
    resource: {
      id: 'sessions'
      partitionKey: {
        paths: ['/conversationId']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/*' }
        ]
        excludedPaths: [
          { path: '/"_etag"/?' }
        ]
      }
      defaultTtl: -1
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
          privateLinkServiceId: cosmosDb.id
          groupIds: ['Sql']
        }
      }
    ]
  }
}

// Private DNS Zone for Cosmos DB
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.documents.azure.com'
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
        name: 'cosmos-dns'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

output id string = cosmosDb.id
output name string = cosmosDb.name
output endpoint string = cosmosDb.properties.documentEndpoint
