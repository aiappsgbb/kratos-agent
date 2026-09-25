@description('Name of the Azure Monitor health model')
param name string

@description('Location of the Azure Monitor health model')
param location string

@description('Resource tags')
param tags object = {}

@description('Resource catalog keyed by logical downstream key')
param resourceCatalog object

@description('Topology graph for advisors, tools, downstream services, and resources')
param topology object = loadJsonContent('../health-model/topology.json')

@description('Signal catalog keyed by metric namespace')
param signalCatalog object = loadJsonContent('../health-model/signals.json')

var monitoringReaderRoleId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var authSettingName = 'auth-health-model'
var Y_STEP = 193
var CENTER_X = 0
var X_STEP = 250

// Sanitize a topology key into a valid CloudHealth entity name segment.
// Also neutralize ARM reserved words (microsoft/azure/windows) which are
// rejected in resource names; the human-readable name stays in displayName.
func collapseDashes(s string) string => replace(replace(replace(replace(replace(replace(s, '--', '-'), '--', '-'), '--', '-'), '--', '-'), '--', '-'), '--', '-')
func san(s string) string => collapseDashes(replace(replace(replace(replace(replace(replace(replace(replace(trim(toLower(s)), ':', '-'), '/', '-'), '.', '-'), '_', '-'), ' ', '-'), 'microsoft', 'msft'), 'azure', 'az'), 'windows', 'win'))

func canvasX(order array, key string) int => CENTER_X + ((2 * indexOf(order, key) - (length(order) - 1)) * X_STEP) / 2

var advisorToolEntries = flatten(map(topology.advisors, advisor => map(advisor.tools, tool => {
  advisorKey: advisor.key
  toolKey: tool.key
  toolDisplayName: tool.displayName
  toolKind: tool.kind
  downstreams: tool.downstreams
})))

var toolDisplayNameMap = reduce(advisorToolEntries, {}, (cur, tool) => union(cur, {
  '${tool.toolKey}': tool.toolDisplayName
}))

var serviceEntries = flatten(map(advisorToolEntries, tool => map(tool.downstreams, downstream => {
  toolKey: tool.toolKey
  serviceKey: downstream.key
  serviceDisplayName: downstream.displayName
  serviceKind: downstream.kind
  resourceKey: downstream.?resourceKey
})))

var serviceMap = reduce(serviceEntries, {}, (cur, service) => union(cur, {
  '${service.serviceKey}': {
    displayName: service.serviceDisplayName
    kind: service.serviceKind
    resourceKey: service.resourceKey
  }
}))

var rootToAdvisorRels = [for advisor in topology.advisors: {
  parent: healthModel.name
  child: 'adv-${advisor.key}'
}]

var advisorToToolCandidates = flatten(map(topology.advisors, advisor => map(advisor.tools, tool => {
  parent: 'adv-${advisor.key}'
  child: 'tool-${san(tool.key)}'
})))

var advisorToToolMap = reduce(advisorToToolCandidates, {}, (cur, rel) => union(cur, {
  '${rel.parent}|${rel.child}': rel
}))

var advisorToToolRels = [for rel in items(advisorToToolMap): rel.value]

var toolToServiceCandidates = map(serviceEntries, service => {
  parent: 'tool-${san(service.toolKey)}'
  child: 'svc-${san(service.serviceKey)}'
})

var toolToServiceMap = reduce(toolToServiceCandidates, {}, (cur, rel) => union(cur, {
  '${rel.parent}|${rel.child}': rel
}))

var toolToServiceRels = [for rel in items(toolToServiceMap): rel.value]

var serviceToResourceCandidates = map(filter(items(serviceMap), service => service.value.kind == 'AzureResource' && !empty(resourceCatalog[?service.value.resourceKey].?azureResourceId)), service => {
  parent: 'svc-${san(service.key)}'
  child: 'res-${service.value.resourceKey}'
  serviceKey: service.key
  resourceKey: service.value.resourceKey
})

var resolvedServiceKeys = map(serviceToResourceCandidates, rel => rel.serviceKey)

var serviceToResourceMap = reduce(serviceToResourceCandidates, {}, (cur, rel) => union(cur, {
  '${rel.parent}|${rel.child}': {
    parent: rel.parent
    child: rel.child
  }
}))

var serviceToResourceRels = [for rel in items(serviceToResourceMap): rel.value]

var relationshipCandidates = concat(rootToAdvisorRels, advisorToToolRels, toolToServiceRels, serviceToResourceRels)

var relationshipMap = reduce(relationshipCandidates, {}, (cur, rel) => union(cur, {
  '${rel.parent}|${rel.child}': rel
}))

var relationships = [for rel in items(relationshipMap): rel.value]

var resourceKeys = filter(topology.layoutOrder.resource, resourceKey => !empty(resourceCatalog[?resourceKey].?azureResourceId))

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
  tags: tags
}

resource uamiRgRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, uami.id, monitoringReaderRoleId)
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleId)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource healthModel 'Microsoft.CloudHealth/healthmodels@2026-05-01-preview' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {}
}

resource authSetting 'Microsoft.CloudHealth/healthmodels/authenticationsettings@2026-05-01-preview' = {
  parent: healthModel
  name: authSettingName
  properties: {
    authenticationKind: 'ManagedIdentity'
    managedIdentityName: uami.id
  }
}

// Root entity = the model itself (advisor edges use parentEntityName == the model
// name). Declared explicitly so it is positioned centered above the advisor tier;
// without an explicit canvasPosition the root defaults to (0,0), far left of the graph.
resource rootEnt 'Microsoft.CloudHealth/healthmodels/entities@2026-05-01-preview' = {
  parent: healthModel
  name: name
  properties: {
    displayName: 'Kratos agent'
    impact: 'Standard'
    tags: {
      tier: 'root'
    }
    canvasPosition: {
      x: CENTER_X
      y: 0
    }
    signalGroups: {
      dependencies: {
        aggregationType: 'WorstOf'
      }
    }
  }
}

resource advisorEnt 'Microsoft.CloudHealth/healthmodels/entities@2026-05-01-preview' = [for advisor in topology.advisors: {
  parent: healthModel
  name: 'adv-${advisor.key}'
  properties: {
    displayName: advisor.displayName
    impact: 'Standard'
    tags: {
      tier: 'advisor'
    }
    canvasPosition: {
      x: canvasX(topology.layoutOrder.advisor, advisor.key)
      y: Y_STEP
    }
    signalGroups: {
      dependencies: {
        aggregationType: 'WorstOf'
      }
    }
  }
}]

resource toolEnt 'Microsoft.CloudHealth/healthmodels/entities@2026-05-01-preview' = [for toolKey in topology.layoutOrder.tool: {
  parent: healthModel
  name: 'tool-${san(toolKey)}'
  properties: {
    displayName: string(toolDisplayNameMap[toolKey])
    impact: 'Standard'
    tags: {
      tier: 'tool'
    }
    canvasPosition: {
      x: canvasX(topology.layoutOrder.tool, toolKey)
      y: 2 * Y_STEP
    }
    signalGroups: {
      dependencies: {
        aggregationType: 'WorstOf'
      }
    }
  }
}]

resource svcEnt 'Microsoft.CloudHealth/healthmodels/entities@2026-05-01-preview' = [for serviceKey in topology.layoutOrder.service: {
  parent: healthModel
  name: 'svc-${san(serviceKey)}'
  properties: {
    displayName: string(serviceMap[serviceKey].displayName)
    impact: contains(resolvedServiceKeys, serviceKey) ? 'Standard' : 'Limited'
    tags: {
      tier: 'service'
    }
    canvasPosition: {
      x: canvasX(topology.layoutOrder.service, serviceKey)
      y: 3 * Y_STEP
    }
  }
}]

resource resEnt 'Microsoft.CloudHealth/healthmodels/entities@2026-05-01-preview' = [for resourceKey in resourceKeys: {
  parent: healthModel
  name: 'res-${resourceKey}'
  properties: {
    displayName: resourceKey
    impact: 'Standard'
    tags: {
      tier: 'resource'
    }
    canvasPosition: {
      x: canvasX(resourceKeys, resourceKey)
      y: 4 * Y_STEP
    }
    signalGroups: {
      azureResource: {
        authenticationSetting: authSetting.name
        azureResourceId: resourceCatalog[resourceKey].azureResourceId
        signals: [for s in (signalCatalog[?resourceCatalog[resourceKey].metricNamespace] ?? []): {
          name: s.name
          signalKind: 'AzureResourceMetric'
          metricNamespace: resourceCatalog[resourceKey].metricNamespace
          metricName: s.metricName
          aggregationType: s.aggregationType
          timeGrain: s.timeGrain
          refreshInterval: s.refreshInterval
          dataUnit: s.dataUnit
          evaluationRules: {
            degradedRule: s.degradedRule
            unhealthyRule: s.unhealthyRule
          }
        }]
      }
    }
  }
}]

resource rels 'Microsoft.CloudHealth/healthmodels/relationships@2026-05-01-preview' = [for rel in relationships: {
  parent: healthModel
  name: 'rel-${uniqueString(rel.parent, rel.child)}'
  properties: {
    parentEntityName: rel.parent
    childEntityName: rel.child
  }
  dependsOn: [
    rootEnt
    advisorEnt
    toolEnt
    svcEnt
    resEnt
  ]
}]

output id string = healthModel.id
output name string = healthModel.name
