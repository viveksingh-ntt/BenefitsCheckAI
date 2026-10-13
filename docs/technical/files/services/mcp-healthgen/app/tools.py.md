# `services/mcp-healthgen/app/tools.py`

Source: [`services/mcp-healthgen/app/tools.py`](../../../../../../services/mcp-healthgen/app/tools.py)

> **Summary:** The 12 MCP tools that Foundry agents call to read and change HealthGen data. Each tool is scoped by `session_ref`, writes need user confirmation, and card data is built from system-of-record responses.

| | |
| --- | --- |
| Layer | MCP data spoke (HealthGen service) |
| Called by | `healthgen-benefit-check` (11 tools) and `healthgen-triage` (`request_human_handoff` only). Locally, the scripted `foundry-local` calls them. |
| Calls | Broker (`/oauth2/token`, `/v1/actions`), HealthGen core, n8n webhook |

## Tools

| Tool | Kind | Core calls | Returns |
| --- | --- | --- | --- |
| `get_member_summary` | read | member, eligibility | audience, first name, plan, coverage dates, PCP, home ZIP |
| `check_benefits(service_ref? \| category?)` | read | benefits (+ member) | benefit rows; with one service, a `card_ref` (benefit-coverage@1) |
| `get_accumulators` | read | accumulators | deductible and out-of-pocket met and remaining |
| `search_services(query, zip?, radius_miles=5)` | read | services, member, benefits | services; `card_ref` (service-options@1, cosmetic excluded) |
| `check_prior_auth(service_ref)` | read | prior-auth | prior-auth and referral flags |
| `find_providers(service_ref, zip?, radius_miles=5, accepting_new_patients_only)` | read | member, providers, benefits | providers nearest first; `card_ref` (provider-results@1, audience from the role) |
| `get_availability(provider_ref, service_ref)` | read | provider, availability, benefits | slots; `card_ref` (availability-slots@1) |
| `prepare_appointment_request(provider_ref, slot_ref, service_ref)` | prepare (members only) | provider, availability (slot still open), benefits (covered) | `action_id`; `card_ref` (booking-review@1) |
| `submit_appointment_request(action_id)` | **write** | `POST /v1/appointments/requests` with the broker's params and note | appointment ref and status; `card_ref` (confirmation@1) |
| `prepare_referral(to_provider_ref, service_ref, visits=1)` | prepare (providers only) | member, provider (offers the service), benefits | `action_id`; `card_ref` (referral-review@1) |
| `submit_referral(action_id)` | **write** | `POST /v1/referrals` | referral ref and status; `card_ref` (confirmation@1) |
| `request_human_handoff(reason, topic)` | external | n8n webhook (signed) | `ticket_ref`, queue, expected response |

## Design rules built into the tools

- **Validated arguments.** Every tool's first argument is `session_ref`, validated as `^ses_[0-9a-f]{32}$`. Refs are validated by pattern (`svc_`, `prv_`, `slt_`, `act_`). No tool takes a member id, and the JSON schema shown to the model contains none.
- **Exchange per call.** Each call exchanges the session ref for a member-scoped core token with only the scopes it needs. Read grants are cached briefly in `clients.py`.
- **Annotations.** The tools carry `read_only_hint`, `destructive_hint` and `idempotent_hint`, so Foundry and MCP clients can show risk.
- **Safe errors.** Errors become `ToolError("code: friendly text")` (`FRIENDLY`), so the model can explain them without seeing internal details.
- **Writes are two-step.** `submit_*` uses the parameters that the broker returns from the confirmed action, not anything the model passes.

## How it's used in the real system

- **Real core:** with the real HealthGen core, keep the same core HTTP contract (see [`healthgen-core-mock/README`](../../../../files/services/healthgen-core-mock/README.md.md)), or adapt the paths in this file.
- **Adding a tool:** add the tool here, add its name to `allowed_tools` in the agent YAML, and add the scope to `READ_SCOPES` in the broker if it is new.

## Related

[`cards.py`](cards.py.md) · [`clients.py`](clients.py.md) · [`main.py`](main.py.md) · [`agents/benefit-check.yaml`](../../../../files/agents/benefit-check.yaml.md) · sequences [2](../../../../sequences.md#2-a-benefit-check-question), [4](../../../../sequences.md#4-booking-with-human-confirmation), [6](../../../../sequences.md#6-hand-off-to-a-care-specialist)
