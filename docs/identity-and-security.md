# Identity and security

## The problem this design solves

Members and providers sign in with the in-house IdM, not Entra ID. Foundry, APIM and MCP authenticate services with Entra ID, and Foundry passes no end-user identity to MCP tools. So the end user's identity must not depend on the model. It has to travel from the portal to the system of record through infrastructure the model cannot influence.

## Credentials

| Credential | Issued by | Holder → audience | Lifetime | Contents |
| --- | --- | --- | --- | --- |
| Portal assertion | Portal BFF (portal key) | BFF → broker (`healthgen-identity-broker`) | ≤ 10 min | `sub`, `role`, `member_ref` (provider: patient in context), `idm_session` |
| Direct Line token | Direct Line (secret held by the broker) | Widget → Direct Line | 60 min, refreshable | Bound to `dl_<random>` (enhanced authentication) |
| `session_ref` | Broker | Relay → agents → MCP | Session (idle 60 min, max 12 h) | Opaque random 128-bit ref, nothing else |
| User-context JWT | Broker (Key Vault HSM key) | Relay → APIM (`healthgen-agent-gateway`) | 10 min | `sid`, `role`, `portal` |
| Downstream JWT | Broker, RFC 8693 exchange | MCP → core (`healthgen-core`) | 5 min | `sub`, `role`, `member_ref`, `scope`, `act`; plus `confirmed_action` on write tokens |
| Service credentials | Entra ID (managed identities) | Relay/MCP/APIM → broker, APIM, MCP, Foundry | ~1 h | `azp`/`appid` checked against an allowlist |

## Rules that do not depend on the model

1. **Who the user is.** It comes from the broker binding `dl_user_id → portal subject`. Direct Line enhanced authentication stops clients from posting as another `from.id`. The relay also checks that the conversation matches the binding. Member refs in the widget's `context` event are display-only and ignored.
2. **What data a tool can touch.** MCP tools accept `session_ref` and never a member id. The broker exchanges it for a token scoped to exactly one member. The core enforces `member_ref` on every route, and for providers it checks that the patient is on their panel. A prompt-injected "show me member X" has nothing to pass.
3. **Writes need a person.** The only path to a write scope is: a review card that MCP created → a Confirm press that arrives at the relay as a Direct Line activity from the bound user → broker `confirm` → a one-time token whose `confirmed_action.params_sha256` the core checks against the request body. The token is single use (`jti`).
4. **Cards are system-of-record data.** `card_ref`s are bound to the session. The relay renders only allow-listed templates.
5. **The gateway limits what the relay can ask Foundry for.** APIM accepts only the triage agent by reference, with no ad-hoc `model`, `instructions` or `tools`. It also enforces a live session (with revocation through the broker), rate limits per session and a size limit, with optional Prompt Shields.
6. **PHI hygiene.** The relay masks SSN-shaped numbers, long id numbers and internal refs in outbound text, and logs only text lengths. The broker stores refs, not PHI. The plan FAQ agent has no PHI tools. The hand-off webhook carries a session ref and a neutral topic, signed with HMAC and a 5-minute timestamp window.

## Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt injection asks for another member's data | No tool takes member ids; member scope is fixed by the token exchange. |
| Prompt injection tries to book or submit | Writes need a broker confirmation that only a card press creates. The core verifies the hash and single use. |
| Model invents card content | Cards are built server-side from core data. The model only passes a `card_ref`. |
| Stolen Direct Line token | Bound to one conversation and one `dl_` user, 60 minutes long. Trusted origins are set on the Direct Line site. Portal logout revokes the session at the broker, and APIM checks status every 60 s. |
| Compromised relay | Has no Foundry data-plane rights (APIM's identity calls Foundry), can invoke only the triage agent, and can confirm only actions that are pending in a live session. |
| Compromised MCP server | Can exchange only for sessions that exist. Write tokens need prior user confirmations. The core enforces scope. Rotate the broker's allowlist entry to cut it off. |
| Replay of a confirmation | Broker state machine (pending → confirmed → consumed) plus the core's `jti` check. |
| Data exfiltration in replies | Output masking; the plan FAQ agent has no PHI; Foundry content filters and optional APIM content safety. |

## Production follow-ups

- **Shared state:** move broker state (SQLite) and the MCP card store (in-memory) to a shared store (Azure Cache for Redis or Cosmos DB) before running more than one replica.
- **Private endpoints:** put Foundry, Search and Key Vault on private endpoints. Foundry's Standard setup with VNet injection lets the MCP tool reach a private APIM or MCP endpoint.
- **Agent identities:** Foundry agent identities let the triage agent call specialists with least privilege (`AgenticIdentityToken` connections). Review the role assignments per agent.
- **Signing keys:** rotate the broker signing key by adding a new Key Vault key version and publishing both public keys in the JWKS for one token lifetime. The current code publishes the configured key only, so add the old key to the JWKS during rotation.
