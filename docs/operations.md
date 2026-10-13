# Operations

## State, and the limits it puts on scaling

| Component | State | Pilot setting | Before scaling out |
| --- | --- | --- | --- |
| Identity broker | Session bindings and pending actions (SQLite in `/tmp`) | 1 replica | Move to Azure Cache for Redis or Cosmos DB (same `SqliteStore` methods). A restart today ends all sessions, and the widget starts a new conversation. |
| MCP data spoke | Card store (in memory, 30 min TTL) | 1 replica | Move to Redis. A restart today makes older cards unavailable; the reply text still arrives. |
| Agent relay | Direct Line → Foundry conversation map (in memory) | 1 to 3 replicas with sticky sessions | Move to Redis. A lost entry only starts a new Foundry conversation. |
| Core mock | Bookings and referrals (in memory) | 1 replica | Replace with the real core. |

## Logs and telemetry

- **No conversation content in logs.** Services log refs and codes only. The relay logs `<N chars>` instead of text.
- **Useful log lines:**
  - broker: `session … bound`, `action … confirmed`, `action … consumed by mcp-healthgen`;
  - core: `appointment APT-… booked (confirmation act_…, session ses_…)`;
  - relay: `agent turn 2.3s envelope=ok|fallback`.
- **Foundry tracing.** Connect the project to Application Insights to see each agent run, A2A call and MCP tool call.
- **Alerts:**
  - relay `agent turn failed` above 2% over 15 minutes;
  - broker 5xx;
  - MCP `upstream_unreachable`;
  - APIM 401/403 spikes, which usually mean an identity or role was misconfigured after a change.

## Changing agents

Edit the YAML, run `deploy_agents.py --dry-run`, then run it for real. Each run creates a new agent version. Pin `FOUNDRY_AGENT_VERSION` on the relay in production, and roll forward by changing it, so a prompt change goes out as a deploy, not instantly.

## Changing cards

The relay owns the templates in `services/agent-relay/templates`. The MCP builders in `services/mcp-healthgen/app/cards.py` own the data shape. Version templates by id (`booking-review@2`) instead of editing them in place, because cards already shown keep their verbs.
