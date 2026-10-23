# Deployment runbook (Azure CLI)

This runbook deploys the pilot as a small set of Azure resources, step by step, without Terraform. Run it from the repo root in Bash with Azure CLI 2.70+ (`az login`, and `az extension add -n containerapp -n bot` if prompted).

Steps marked ⚠️ were written from the documentation and not yet run against a subscription. Check the result before moving on.

| # | Step | Creates |
| --- | --- | --- |
| 0 | Variables | |
| 1 | Foundations | Resource group, Log Analytics, Key Vault (Premium), ACR, VNet |
| 2 | Identities and Entra apps | 4 user-assigned managed identities, 3 API app registrations |
| 3 | Broker signing key | RSA-HSM key in Key Vault |
| 4 | Images | 4 container images |
| 5 | Container Apps | Environment plus core-mock, broker, MCP, relay |
| 6 | AI Search | Service, index, documents |
| 7 | Foundry | Account, project, model, connections, agents, A2A, roles |
| 8 | Azure Bot and Direct Line | Bot with managed identity, Direct Line site with enhanced auth |
| 9 | APIM | Agent gateway API and MCP gateway API, policies, named values |
| 10 | Wire everything | Final environment variables on the apps |
| 11 | n8n hand-off | Workflow import, secrets |
| 12 | Portal integration | BFF token endpoint, widget configuration |
| 13 | Smoke tests | |

> **AG-UI instead of Bot Service and Direct Line?** Follow this runbook, skip step 8, and apply the delta in [ag-ui.md](ag-ui.md#deploy-delta-to-the-runbook).

## 0. Variables

```bash
export LOCATION=eastus2
export RG=rg-healthgen-agents
export SUFFIX=hg$RANDOM                      # keep this value; names must be globally unique
export KV=kv-$SUFFIX ACR=acr$SUFFIX LAW=law-$SUFFIX
export ENV_NAME=cae-healthgen VNET=vnet-healthgen
export SEARCH=srch-$SUFFIX SEARCH_INDEX=healthgen-plan-docs
export AIF=aif-$SUFFIX PROJECT=healthgen MODEL=gpt-4.1
export APIM=apim-$SUFFIX APIM_EMAIL=you@example.com
export BOT=bot-healthgen
export PORTAL_ORIGINS="https://members.example.com,https://providers.example.com"
export TENANT_ID=$(az account show --query tenantId -o tsv)
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

## 1. Foundations

```bash
az group create -n $RG -l $LOCATION
az monitor log-analytics workspace create -g $RG -n $LAW -l $LOCATION
az keyvault create -g $RG -n $KV -l $LOCATION --sku premium --enable-rbac-authorization true
az acr create -g $RG -n $ACR --sku Standard
az network vnet create -g $RG -n $VNET --address-prefixes 10.40.0.0/16 \
  --subnet-name snet-apps --subnet-prefixes 10.40.0.0/23
az network vnet subnet update -g $RG --vnet-name $VNET -n snet-apps --delegations Microsoft.App/environments
az network vnet subnet create -g $RG --vnet-name $VNET -n snet-apim --address-prefixes 10.40.4.0/24 \
  --delegations Microsoft.Web/serverFarms
```

Give yourself rights to create keys and secrets:

```bash
ME=$(az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee $ME --role "Key Vault Administrator" --scope $(az keyvault show -n $KV --query id -o tsv)
```

## 2. Identities and Entra app registrations

There is one user-assigned managed identity per workload, plus one for the bot.

```bash
for id in relay broker mcp bot; do az identity create -g $RG -n id-$id; done
cid() { az identity show -g $RG -n id-$1 --query clientId -o tsv; }
pid() { az identity show -g $RG -n id-$1 --query principalId -o tsv; }
rid() { az identity show -g $RG -n id-$1 --query id -o tsv; }
```

Three API app registrations give the services their token audiences. Managed identities request tokens for these audiences, and each receiver checks `azp`/`appid` against its allowlist.

```bash
for api in healthgen-identity-broker healthgen-mcp healthgen-agent-gateway; do
  az ad app create --display-name $api --identifier-uris api://$api --sign-in-audience AzureADMyOrg
  az ad sp create --id $(az ad app list --display-name $api --query [0].appId -o tsv)
done
```

All identities can pull images:

```bash
ACR_ID=$(az acr show -n $ACR --query id -o tsv)
for id in relay broker mcp; do az role assignment create --assignee-object-id $(pid $id) --assignee-principal-type ServicePrincipal --role AcrPull --scope $ACR_ID; done
```

## 3. Broker signing key (HSM)

```bash
az keyvault key create --vault-name $KV -n broker-signing --kty RSA-HSM --size 2048 --ops sign verify
export BROKER_KEY_ID=$(az keyvault key show --vault-name $KV -n broker-signing --query key.kid -o tsv)   # includes the version
az role assignment create --assignee-object-id $(pid broker) --assignee-principal-type ServicePrincipal \
  --role "Key Vault Crypto User" --scope $(az keyvault show -n $KV --query id -o tsv)
```

Keep the versioned key id. The JWT `kid` is the version, so rotating means a new version plus a redeploy (see identity-and-security.md).

## 4. Build the images

```bash
for s in healthgen-core-mock identity-broker mcp-healthgen agent-relay; do
  az acr build -r $ACR -t healthgen/$s:0.1.0 services/$s
done
```

⚠️ The relay image installs the M365 Agents SDK packages from `requirements-host.txt`. Pin the versions that install cleanly, then rebuild.

## 5. Container Apps

```bash
az containerapp env create -g $RG -n $ENV_NAME -l $LOCATION \
  --logs-workspace-id $(az monitor log-analytics workspace show -g $RG -n $LAW --query customerId -o tsv) \
  --logs-workspace-key $(az monitor log-analytics workspace get-shared-keys -g $RG -n $LAW --query primarySharedKey -o tsv) \
  --infrastructure-subnet-resource-id $(az network vnet subnet show -g $RG --vnet-name $VNET -n snet-apps --query id -o tsv)
DOMAIN=$(az containerapp env show -g $RG -n $ENV_NAME --query properties.defaultDomain -o tsv)
export CORE_URL=https://ca-core.internal.$DOMAIN BROKER_URL=https://ca-broker.internal.$DOMAIN
export MCP_URL=https://ca-mcp.internal.$DOMAIN RELAY_URL=https://ca-relay.$DOMAIN
```

The pilot runs **one replica** of the broker and MCP, because they hold SQLite and in-memory state (see operations.md).

```bash
IMG=$ACR.azurecr.io/healthgen
# HealthGen core mock (internal). Replace it with the real core later: only CORE_URL changes.
az containerapp create -g $RG -n ca-core --environment $ENV_NAME --image $IMG/healthgen-core-mock:0.1.0 \
  --user-assigned $(rid broker) --registry-server $ACR.azurecr.io --registry-identity $(rid broker) \
  --ingress internal --target-port 8101 --min-replicas 1 --max-replicas 1 \
  --env-vars BROKER_ISSUER=$BROKER_URL CORE_JWKS_URL=$BROKER_URL/.well-known/jwks.json

# Identity broker (internal). Direct Line secret and service clients are added in step 10.
az containerapp create -g $RG -n ca-broker --environment $ENV_NAME --image $IMG/identity-broker:0.1.0 \
  --user-assigned $(rid broker) --registry-server $ACR.azurecr.io --registry-identity $(rid broker) \
  --ingress internal --target-port 8102 --min-replicas 1 --max-replicas 1 \
  --env-vars BROKER_ISSUER=$BROKER_URL BROKER_KEYVAULT_KEY_ID=$BROKER_KEY_ID AZURE_CLIENT_ID=$(cid broker) \
    SERVICE_AUTH=entra ENTRA_TENANT_ID=$TENANT_ID BROKER_ENTRA_AUDIENCES=api://healthgen-identity-broker \
    BROKER_DB_PATH=/tmp/broker.db DIRECTLINE_SECRET=pending PORTAL_ISSUERS=pending PORTAL_JWKS_URL=https://pending.invalid SERVICE_CLIENTS=pending=pending

# MCP data spoke (internal; APIM fronts it for Foundry)
az containerapp create -g $RG -n ca-mcp --environment $ENV_NAME --image $IMG/mcp-healthgen:0.1.0 \
  --user-assigned $(rid mcp) --registry-server $ACR.azurecr.io --registry-identity $(rid mcp) \
  --ingress internal --target-port 8103 --min-replicas 1 --max-replicas 1 \
  --env-vars BROKER_URL=$BROKER_URL CORE_URL=$CORE_URL BROKER_ENTRA_RESOURCE=api://healthgen-identity-broker AZURE_CLIENT_ID=$(cid mcp) \
    MCP_AUTH=entra ENTRA_TENANT_ID=$TENANT_ID MCP_AUDIENCES=api://healthgen-mcp MCP_CLIENTS=pending=pending \
    INTERNAL_AUTH=entra INTERNAL_AUDIENCES=api://healthgen-mcp INTERNAL_CLIENTS=agent-relay=$(cid relay) \
    MCP_ALLOWED_HOSTS=ca-mcp.internal.$DOMAIN,ca-mcp.internal.$DOMAIN:443

# Agent relay (external: Azure Bot Service must reach /api/messages). Bot settings are added in step 8.
az containerapp create -g $RG -n ca-relay --environment $ENV_NAME --image $IMG/agent-relay:0.1.0 \
  --user-assigned $(rid relay) $(rid bot) --registry-server $ACR.azurecr.io --registry-identity $(rid relay) \
  --ingress external --target-port 3978 --min-replicas 1 --max-replicas 3 \
  --env-vars BROKER_URL=$BROKER_URL BROKER_RESOURCE=api://healthgen-identity-broker \
    MCP_URL=$MCP_URL MCP_CARDS_RESOURCE=api://healthgen-mcp AZURE_CLIENT_ID=$(cid relay) \
    FOUNDRY_AGENT_NAME=healthgen-triage FOUNDRY_RESOURCE=api://healthgen-agent-gateway FOUNDRY_BASE_URL=pending
```

> The relay's per-conversation state (the Foundry conversation id) is in memory. With more than one replica, enable session affinity (`az containerapp ingress sticky-sessions set --affinity sticky`) or move that state to Redis before scaling out. A lost mapping only starts a new Foundry conversation.

## 6. AI Search and plan documents

```bash
az search service create -g $RG -n $SEARCH --sku basic --semantic-search free --auth-options aadOrApiKey --aad-auth-failure-mode http401WithBearerChallenge
SEARCH_ID=$(az search service show -g $RG -n $SEARCH --query id -o tsv)
az role assignment create --assignee $ME --role "Search Service Contributor" --scope $SEARCH_ID
az role assignment create --assignee $ME --role "Search Index Data Contributor" --scope $SEARCH_ID
SEARCH_SERVICE_NAME=$SEARCH SEARCH_INDEX_NAME=$SEARCH_INDEX python search/ingest.py
```

## 7. Foundry: account, project, model, connections, agents

```bash
az cognitiveservices account create -g $RG -n $AIF -l $LOCATION --kind AIServices --sku S0 \
  --custom-domain $AIF --allow-project-management --assign-identity
az cognitiveservices account project create -g $RG --name $AIF --project-name $PROJECT -l $LOCATION   # ⚠️ check `az cognitiveservices account project -h`
az cognitiveservices account deployment create -g $RG -n $AIF --deployment-name $MODEL \
  --model-name gpt-4.1 --model-version 2025-04-14 --model-format OpenAI --sku-name GlobalStandard --sku-capacity 100
export PROJECT_ENDPOINT=https://$AIF.services.ai.azure.com/api/projects/$PROJECT
PROJECT_ID=$(az resource show -g $RG -n $AIF/projects/$PROJECT --resource-type Microsoft.CognitiveServices/accounts/projects --query id -o tsv)
PROJECT_PID=$(az resource show --ids $PROJECT_ID --query identity.principalId -o tsv)
PROJECT_MI_CLIENT=$(az ad sp show --id $PROJECT_PID --query appId -o tsv)
```

Grant the roles:

```bash
# You, to create agents and connections
az role assignment create --assignee $ME --role "Azure AI User" --scope $PROJECT_ID
az role assignment create --assignee $ME --role "Azure AI Project Manager" --scope $PROJECT_ID   # "Foundry Project Manager" after the rename
# The project identity reads the search index (AI Search tool)
az role assignment create --assignee-object-id $PROJECT_PID --assignee-principal-type ServicePrincipal --role "Search Index Data Reader" --scope $SEARCH_ID
```

The MCP connection needs the APIM MCP URL from step 9. Do steps 9.1 and 9.2 first, then come back. After that, deploy the connections and agents:

```bash
cat > agents/foundry.env <<EOF
SUBSCRIPTION_ID=$SUBSCRIPTION_ID
RESOURCE_GROUP=$RG
FOUNDRY_ACCOUNT=$AIF
FOUNDRY_PROJECT=$PROJECT
MODEL_DEPLOYMENT=$MODEL
MCP_SERVER_URL=https://$APIM.azure-api.net/mcp/healthgen/mcp
MCP_AUDIENCE=api://healthgen-mcp
SEARCH_SERVICE_NAME=$SEARCH
SEARCH_INDEX_NAME=$SEARCH_INDEX
EOF
pip install pyyaml
python agents/deploy_agents.py --env-file agents/foundry.env --dry-run   # review
python agents/deploy_agents.py --env-file agents/foundry.env
```

⚠️ **Check these after the first run:**

1. **Connections.** In the Foundry portal (*Management center → Connected resources*), check the four connections. If ARM rejects `healthgen-mcp` (`RemoteTool` / `ProjectManagedIdentity`), create it with the CLI, then run the script again with `--skip-connections`:

   ```bash
   azd ai connection create healthgen-mcp --kind remote-tool --target https://$APIM.azure-api.net/mcp/healthgen/mcp \
     --auth-type project-managed-identity --audience api://healthgen-mcp
   ```

2. **Incoming A2A.** Each specialist must serve its agent card:

   ```bash
   TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
   curl -s -H "Authorization: Bearer $TOKEN" "$PROJECT_ENDPOINT/agents/healthgen-benefit-check/endpoint/protocols/a2a/agentCard/v1.0" | head -c 400
   ```

   If the PATCH failed, copy the body from [Enable incoming A2A on a Foundry agent](https://learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint) into `a2a.enable_body` in the agent's YAML, then run `deploy_agents.py --skip-connections --only healthgen-plan-faq healthgen-benefit-check`.

3. **The triage agent may call the specialists.** Give the calling identity *Foundry Agent Consumer* on the project. With `AgenticIdentityToken` connections, the calling identity is the triage agent's identity. Find its principal id in `GET $PROJECT_ENDPOINT/agents/healthgen-triage?api-version=v1` (`instance_identity.principal_id`) or in the portal.

   ```bash
   az role assignment create --assignee-object-id <triage-agent-principal-id> --assignee-principal-type ServicePrincipal \
     --role eed3b665-ab3a-47b6-8f48-c9382fb1dad6 --scope $PROJECT_ID
   ```

4. **Playground test.** In the Foundry playground, send `healthgen-triage` a test turn with a fake session ref:

   ```
   [turn-context]
   session_ref: ses_00000000000000000000000000000000
   portal: member
   [/turn-context]
   How long is a referral valid?
   ```

   It should route to the plan FAQ and answer with a JSON envelope that cites the EOC.

## 8. Azure Bot and Direct Line

```bash
az bot create -g $RG -n $BOT --app-type UserAssignedMSI --appid $(cid bot) --tenant-id $TENANT_ID \
  --msi-resource-id $(rid bot) --endpoint https://ca-relay.$DOMAIN/api/messages --sku S1
az bot directline create -g $RG -n $BOT --site-name portals --enable-enhanced-auth true \
  --trusted-origins ${PORTAL_ORIGINS//,/ }                              # ⚠️ check flags with `az bot directline create -h`
DL_SECRET=$(az bot directline show -g $RG -n $BOT --with-secrets true --query "properties.properties.sites[0].key" -o tsv)
az keyvault secret set --vault-name $KV -n directline-secret --value "$DL_SECRET" >/dev/null
```

Give the relay its bot identity (M365 Agents SDK):

```bash
az containerapp update -g $RG -n ca-relay --set-env-vars \
  CONNECTIONS__SERVICE_CONNECTION__SETTINGS__AUTHTYPE=UserManagedIdentity \
  CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=$(cid bot) \
  CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=$TENANT_ID
```

Requirements:

- **Enhanced authentication must be on.** It is what binds `from.id` to the token, and the broker's `dl_` user ids depend on it.
- **Trusted origins** must list exactly the portal origins.
- **Disable the Web Chat channel** if you don't use it.

## 9. API Management

### 9.1 Create the instance

```bash
az apim create -g $RG -n $APIM -l $LOCATION --publisher-name HealthGen --publisher-email $APIM_EMAIL \
  --sku-name StandardV2 --enable-managed-identity true          # can take 30+ minutes
APIM_PID=$(az apim show -g $RG -n $APIM --query identity.principalId -o tsv)
APIM_CLIENT=$(az ad sp show --id $APIM_PID --query appId -o tsv)
```

APIM must reach the internal Container Apps. Add outbound VNet integration with the `snet-apim` subnet: in the portal, open *Network → Outbound → VNet integration*. Also add a private DNS zone for `$DOMAIN`, pointing to the environment's static IP.

APIM's identity calls Foundry:

```bash
az role assignment create --assignee-object-id $APIM_PID --assignee-principal-type ServicePrincipal --role "Azure AI User" --scope $PROJECT_ID
```

### 9.2 Named values and APIs

```bash
nv() { az apim nv create -g $RG --service-name $APIM --named-value-id $1 --display-name $1 --value "$2" >/dev/null; }
nv tenant-id $TENANT_ID
nv relay-client-id $(cid relay)
nv broker-issuer $BROKER_URL
nv broker-openid-config-url $BROKER_URL/.well-known/openid-configuration
nv broker-base-url $BROKER_URL
nv triage-agent-name healthgen-triage
nv foundry-project-mi-client-id $PROJECT_MI_CLIENT

az apim api create -g $RG --service-name $APIM --api-id healthgen-agent-gateway --display-name "HealthGen agent gateway" \
  --path foundry --service-url https://$AIF.services.ai.azure.com --protocols https --subscription-required false
az apim api operation create -g $RG --service-name $APIM --api-id healthgen-agent-gateway --operation-id responses \
  --display-name responses --method POST --url-template "/api/projects/{project}/openai/v1/responses" --template-parameters name=project type=string required=true
az apim api operation create -g $RG --service-name $APIM --api-id healthgen-agent-gateway --operation-id conversations \
  --display-name conversations --method POST --url-template "/api/projects/{project}/openai/v1/conversations" --template-parameters name=project type=string required=true

az apim api create -g $RG --service-name $APIM --api-id healthgen-mcp --display-name "HealthGen MCP" \
  --path mcp/healthgen --service-url $MCP_URL --protocols https --subscription-required false
az apim api operation create -g $RG --service-name $APIM --api-id healthgen-mcp --operation-id mcp \
  --display-name mcp --method POST --url-template "/mcp"
```

### 9.3 Policies

```bash
put_policy() {
  az rest --method PUT \
    --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/apis/$1/policies/policy?api-version=2022-08-01" \
    --body "$(python -c 'import json,sys;print(json.dumps({"properties":{"format":"rawxml","value":open(sys.argv[1]).read()}}))' $2)"
}
put_policy healthgen-agent-gateway apim/foundry-gateway.policy.xml
put_policy healthgen-mcp apim/mcp-gateway.policy.xml
```

⚠️ If APIM rejects an expression, open the API in the portal policy editor, which shows the line. Optional: create an Azure AI Content Safety resource and an APIM backend named `content-safety`, then uncomment the `llm-content-safety` block.

### 9.4 Allow-list APIM at the broker and MCP

APIM calls the broker for session status, and calls MCP with its own identity.

```bash
az containerapp update -g $RG -n ca-mcp --set-env-vars MCP_CLIENTS=apim=$APIM_CLIENT
```

The broker's `SERVICE_CLIENTS` is set in step 10.

## 10. Wire everything

```bash
az containerapp secret set -g $RG -n ca-broker --secrets \
  directline-secret=keyvaultref:$(az keyvault secret show --vault-name $KV -n directline-secret --query id -o tsv),identityref:$(rid broker)
az role assignment create --assignee-object-id $(pid broker) --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" \
  --scope $(az keyvault show -n $KV --query id -o tsv)
az containerapp update -g $RG -n ca-broker --set-env-vars \
  DIRECTLINE_SECRET=secretref:directline-secret DIRECTLINE_TRUSTED_ORIGINS=$PORTAL_ORIGINS \
  PORTAL_ISSUERS=https://members.example.com,https://providers.example.com \
  PORTAL_JWKS_URL=https://portal-bff.example.com/.well-known/jwks.json \
  SERVICE_CLIENTS=agent-relay=$(cid relay),mcp-healthgen=$(cid mcp),apim=$APIM_CLIENT

az containerapp update -g $RG -n ca-relay --set-env-vars \
  FOUNDRY_BASE_URL=https://$APIM.azure-api.net/foundry/api/projects/$PROJECT
```

`PORTAL_JWKS_URL` takes one URL. If the member and provider BFFs sign with different keys, publish both keys in one JWKS document.

## 11. n8n hand-off

1. Import `handoff/healthgen-handoff.n8n.json` (*Workflows → Import from file*).
2. On the n8n host, set these environment variables: `HEALTHGEN_HANDOFF_SECRET=<random 32+ bytes>`, `HEALTHGEN_CARE_TEAM_WEBHOOK_URL=<Teams/Slack incoming webhook>` and `NODE_FUNCTION_ALLOW_BUILTIN=crypto`.
3. Replace the *Create ticket* node with your CRM's create-case call when you are ready.
4. Activate the workflow and point MCP at it:

   ```bash
   az keyvault secret set --vault-name $KV -n handoff-secret --value "<same secret>" >/dev/null
   az role assignment create --assignee-object-id $(pid mcp) --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $(az keyvault show -n $KV --query id -o tsv)
   az containerapp secret set -g $RG -n ca-mcp --secrets handoff-secret=keyvaultref:$(az keyvault secret show --vault-name $KV -n handoff-secret --query id -o tsv),identityref:$(rid mcp)
   az containerapp update -g $RG -n ca-mcp --set-env-vars HANDOFF_WEBHOOK_URL=https://<n8n-host>/webhook/healthgen-handoff HANDOFF_WEBHOOK_SECRET=secretref:handoff-secret
   ```

## 12. Portal integration

**Portal backend (each BFF).** Add one endpoint, `POST /api/agent/directline-token`. `clients/portal-dev/server.py` is a working reference.

1. Read the signed-in user from the IdM session.
2. Sign a portal assertion as an RS256 JWT, valid ≤ 10 min, with these claims:
   - `iss` (the portal origin) and `aud=healthgen-identity-broker`;
   - `sub`: the member ref, or the provider user ref;
   - `role`: `member` or `provider`, and `portal`;
   - `member_ref`: for providers, the patient in context, after the portal's own relationship check;
   - `idm_session`, `name` (first name for greetings), `jti`, `iat` and `exp`.
3. POST to `{BROKER}/v1/directline/token` with `Authorization: Bearer <assertion>`, forwarding the widget's JSON body (`reason`, `conversationId`).
4. Return the broker's JSON to the widget.
5. Publish the BFF's public key at the `PORTAL_JWKS_URL`.
6. On logout, POST the same assertion to `{BROKER}/v1/directline/logout`.

The broker is internal. Expose `/v1/directline/*` to the BFFs through a private route, or through an APIM API restricted to the BFFs' network.

**Widget.**

```js
widget.init({ tokenUrl: '/api/agent/directline-token', context: { member: {...display only...}, page: {...} }, allowedRoutes: ['/plan/*', '/care/*', '/providers/*'] })
```

For a regional Direct Line endpoint, set `directLineDomain` (for example `https://europe.directline.botframework.com/v3/directline`).

## 13. Smoke tests

```bash
# Broker publishes its keys; the core can fetch them
az containerapp exec -g $RG -n ca-core --command "python -c \"import urllib.request;print(urllib.request.urlopen('$BROKER_URL/.well-known/jwks.json').read()[:80])\""
# Relay is listening (expects 401 without a Bot Service token)
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://ca-relay.$DOMAIN/api/messages
# APIM blocks callers without credentials
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://$APIM.azure-api.net/foundry/api/projects/$PROJECT/openai/v1/responses
```

Then sign in to the test portal and run the four prototype journeys:

1. Benefit check. Expected: benefit card with a $40 copay for Alex.
2. Service search.
3. Doctor search → availability → review → Confirm. Expected: a confirmation card.
4. Provider portal: doctor search → review referral → submit. Expected: a confirmation card.

Also press "Talk to a person" and check that the care team gets the notification.

**Where to look when something fails:**

| Symptom | Check |
| --- | --- |
| "Your session has ended" | Broker logs: `session not resolved`. Is enhanced auth on? Does the bot use the same Direct Line site the broker generates tokens for? |
| Generic error reply | Relay logs `agent turn failed: <code> (<status>)`. A 401 or 403 from APIM means the `appid`, X-User-Context or session status check failed. |
| Answers but no cards | The agent did not return `card_ref`. Check the benefit-check agent's tool calls in Foundry tracing, and the MCP logs. |
| Tool errors `invalid_grant` | The broker exchange failed: session expired, or MCP's identity is not in `SERVICE_CLIENTS`. |
