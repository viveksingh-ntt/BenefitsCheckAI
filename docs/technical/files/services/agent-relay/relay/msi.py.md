# `services/agent-relay/relay/msi.py`

Source: [`services/agent-relay/relay/msi.py`](../../../../../../services/agent-relay/relay/msi.py)

> **Summary:** Gets Entra access tokens for the container's managed identity, with stdlib HTTP only.

## What it does

`ManagedIdentityCredential(client_id).token(resource)`:

- uses the **Container Apps / App Service identity endpoint** (`IDENTITY_ENDPOINT` plus the `X-IDENTITY-HEADER` header, api-version `2019-08-01`) when one is present;
- otherwise falls back to the **Azure Instance Metadata Service** (`169.254.169.254`);
- caches each token per resource until 5 minutes before it expires.

`AZURE_CLIENT_ID` selects the user-assigned identity.

## How it's used in the real system

The relay uses it to get tokens for:

- the broker (`api://healthgen-identity-broker`);
- the MCP card endpoint (`api://healthgen-mcp`);
- APIM (`api://healthgen-agent-gateway`).

The same class is copied in `services/mcp-healthgen/app/msi.py` and inside `services/identity-broker/app/signer.py`, so each service stays self-contained. If you adopt the Azure SDK later, `azure.identity.ManagedIdentityCredential` can replace it.

Locally it is never used, because `*_KEY` variables take precedence in `token_provider`.
