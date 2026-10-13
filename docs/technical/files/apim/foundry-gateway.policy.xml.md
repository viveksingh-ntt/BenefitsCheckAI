# `apim/foundry-gateway.policy.xml`

Source: [`apim/foundry-gateway.policy.xml`](../../../../apim/foundry-gateway.policy.xml)

> **Summary:** The APIM policy for the **agent gateway** (relay → Foundry). It authenticates the relay and the end-user session, applies guardrails, and calls Foundry with APIM's own managed identity.

| | |
| --- | --- |
| Layer | API gateway |
| Local run | Stand-in: the `gateway()` function in `services/foundry-local/app.py` does the same checks |
| Azure | **Real:** the `healthgen-agent-gateway` API, path `/foundry`, backend `https://{account}.services.ai.azure.com` |
| Status | ⚠️ Check the expressions in the APIM policy editor on import |

## Inbound steps

1. **`validate-jwt` (Authorization):** an Entra token with audience `api://healthgen-agent-gateway` and `appid` equal to `{{relay-client-id}}`.
2. **`validate-jwt` (X-User-Context):** the broker's OpenID configuration, audience `healthgen-agent-gateway`, role `member` or `provider`. Stores `sid`.
3. **Session revocation:** looks up `ses-active-{sid}` in the cache. On a miss it calls `send-request` to `{{broker-base-url}}/v1/sessions/{sid}/status` with APIM's managed identity and caches the result for 60 s. If the session is not active, returns 401.
4. **Guardrails:**
   - `rate-limit-by-key` allows 30 POSTs a minute per session;
   - on `/responses`, only `agent_reference.name == {{triage-agent-name}}`, and no `model`, `instructions` or `tools` (403 otherwise);
   - bodies over 20 KB get 413;
   - an optional `llm-content-safety` block (Prompt Shields), commented out;
   - any path other than `/responses` and `/conversations` gets 404.
5. **Forwarding:** removes `X-User-Context` and the subscription key, gets a token with `authentication-managed-identity` for `https://ai.azure.com`, and sets `x-ms-client-request-id`.

Backend timeout is 150 s. Outbound, it strips internal request-id headers.

## Named values

`tenant-id`, `relay-client-id`, `broker-issuer`, `broker-openid-config-url`, `broker-base-url`, `triage-agent-name` (runbook step 9.2).

## How it's used in the real system

APIM's identity needs **Azure AI User** (Foundry User) on the project. The relay itself has no Foundry rights, so a compromised relay can only invoke the triage agent, for live sessions, within rate limits.
