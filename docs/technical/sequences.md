# Sequence diagrams

These diagrams show how a request moves through every layer of the HealthGen care assistant. Each participant is labelled with what runs in each environment:

| Layer | Local run (`scripts/local_stack.py`) | Pilot in Azure | Production |
| --- | --- | --- | --- |
| Widget | Real (`agent-widget` build, vendored) | Real | Real |
| Portal backend (BFF) | **Local stand-in:** `clients/portal-dev/server.py` | Your portal BFF | Your portal BFF |
| Direct Line | **Local stand-in:** `services/agent-relay/dev_server.py` | Azure Bot Service, Direct Line | Same |
| Agent relay | Real code (`relay/core.py`) inside `dev_server.py` | Real code in `host_m365.py` (M365 Agents SDK) | Same |
| Identity broker | Real code, local RSA key, shared keys | Real code, Key Vault HSM key, Entra service auth | Same, with shared state (Redis or Cosmos DB) |
| APIM gateways | **Local stand-in:** checks in `services/foundry-local/app.py` | Azure API Management (`apim/*.xml`) | Same |
| Foundry agents | **Local stand-in:** scripted router in `foundry-local` (not an LLM) | Foundry prompt agents (`agents/*.yaml`) | Same |
| AI Search | **Local stand-in:** keyword search over `search/documents` | Azure AI Search | Same, with your real plan documents |
| MCP data spoke | Real code | Real code | Same, with a shared card store |
| HealthGen core | **Mock:** `services/healthgen-core-mock` | **Mock** | Real HealthGen core APIs |
| Hand-off | **Local stand-in:** stub route in `foundry-local` | n8n workflow (`handoff/`) | n8n plus your CRM |

Each diagram is also exported as an SVG in [`images/`](images/) for Confluence, wikis or slides. Regenerate them with `mmdc` (mermaid-cli) after you edit a diagram.

How to read the diagrams:

- The coloured boxes group the participants.
  - **Green:** code from this repo that runs unchanged everywhere.
  - **Blue:** a managed service or portal piece that has a local stand-in.
  - **Grey:** the system of record, which is mocked until production.
- Participant names say **[local: …]** when a stand-in replaces the real thing on a laptop.
- `rect` shading marks the security checks that do not depend on the model.

Contents:

1. [Start a chat session](#1-start-a-chat-session)
2. [A benefit-check question](#2-a-benefit-check-question)
3. [Pressing a card button](#3-pressing-a-card-button)
4. [Booking with human confirmation](#4-booking-with-human-confirmation)
5. [Provider referral](#5-provider-referral)
6. [Hand-off to a care specialist](#6-hand-off-to-a-care-specialist)
7. [Resume, token refresh and logout](#7-resume-token-refresh-and-logout)
8. [Failures and guardrails](#8-failures-and-guardrails)
9. [Deploying agents and plan documents](#9-deploying-agents-and-plan-documents)
10. [Local stack and automated tests](#10-local-stack-and-automated-tests)

---

## 1. Start a chat session

The widget never sees a Direct Line secret or a member id from the server. The broker generates a Direct Line token for a random `dl_` user and records which portal user it belongs to. Direct Line enhanced authentication then makes that `dl_` id the only identity the widget can post as.

```mermaid
sequenceDiagram
  autonumber
  box rgb(227,242,253) Portal
    participant W as Widget (browser)
    participant BFF as Portal BFF<br/>[local: portal-dev/server.py]
  end
  box rgb(232,245,233) HealthGen services
    participant IB as Identity broker
  end
  box rgb(227,242,253) Managed
    participant DL as Direct Line<br/>[local: dev_server.py]
  end

  W->>BFF: POST /api/agent/directline-token {reason:"start"} (portal session cookie)
  BFF->>BFF: Read the signed-in user from the IdM session
  BFF->>BFF: Sign portal assertion (RS256, ≤10 min): sub, role, member_ref, idm_session, name
  BFF->>IB: POST /v1/directline/token, Bearer assertion
  rect rgb(255,248,225)
    IB->>BFF: GET /.well-known/jwks.json (cached)
    IB->>IB: Verify signature, issuer, audience, lifetime ≤10 min, and that a member acts only for themselves
  end
  IB->>DL: POST /v3/directline/tokens/generate (Bearer channel secret)<br/>{user:{id:"dl_<random>"}, trustedOrigins}
  DL-->>IB: {conversationId, token, expires_in}
  IB->>IB: Store binding: session_ref ↔ dl_user ↔ conversation ↔ portal user
  IB-->>BFF: {token, conversationId, expires_in, userId:"dl_…"}
  BFF-->>W: same JSON
  W->>DL: POST /v3/directline/conversations (Bearer token)
  DL-->>W: {conversationId, streamUrl?}<br/>(local emulator: no streamUrl, so the widget polls)
  W->>DL: event "context" {locale, page, member (display only)}
```

<sub>Rendered image for wikis and slides: [images/01-start-session.svg](images/01-start-session.svg)</sub>

**In Azure:** Direct Line is Azure Bot Service with enhanced authentication and trusted origins set to the portal origins (runbook step 8). The broker signs with Key Vault and authenticates services with Entra ID.

**Locally:** `dev_server.py` imitates the same endpoints and forces `from.id` to the token's user, which is the behaviour enhanced authentication gives in Azure.

---

## 2. A benefit-check question

This is the main path: one user message going through every layer and coming back as a reply, an Adaptive Card and suggestion chips.

```mermaid
sequenceDiagram
  autonumber
  box rgb(227,242,253) Portal
    participant W as Widget
  end
  box rgb(227,242,253) Managed
    participant DL as Direct Line<br/>[local: dev_server.py]
  end
  box rgb(232,245,233) HealthGen services
    participant R as Agent relay<br/>(relay/core.py)
    participant IB as Identity broker
  end
  box rgb(227,242,253) Managed
    participant G as APIM agent gateway<br/>[local: foundry-local checks]
    participant T as Triage agent<br/>[local: scripted router]
    participant B as Benefit-check agent<br/>[local: scripted router]
    participant S as AI Search<br/>[local: keyword search]
  end
  box rgb(232,245,233) HealthGen services
    participant M as MCP data spoke
  end
  box rgb(238,238,238) System of record
    participant C as HealthGen core<br/>[mock until production]
  end

  W->>DL: message "Is a skin check covered?"
  DL->>R: activity (from.id = dl_…, conversation.id)
  rect rgb(255,248,225)
    R->>IB: POST /v1/sessions/resolve {dl_user_id, conversation_id}
    IB-->>R: session_ref, role, portal, display_name, user-context JWT (10 min)
  end
  R-->>DL: typing (streaminfo informative "Checking…")
  DL-->>W: progress line
  R->>G: POST /openai/v1/conversations (first turn only)
  R->>G: POST /openai/v1/responses<br/>{agent_reference: healthgen-triage, conversation, input: [turn-context] + text}<br/>Authorization: relay MI · X-User-Context: JWT
  rect rgb(255,248,225)
    G->>G: validate relay identity, validate user-context JWT, session active? (broker, cached 60 s)
    G->>G: only the triage agent, no model/instructions/tools overrides, rate limit per session
  end
  G->>T: forward with APIM managed identity
  T->>B: A2A 1.0 message: [turn-context] session_ref … + request
  B->>M: MCP tools/call search_services(session_ref, "skin check")
  rect rgb(255,248,225)
    M->>IB: POST /oauth2/token (RFC 8693, subject_token = session_ref, scope = …read)
    IB-->>M: downstream JWT: sub, member_ref, role, scope, act=mcp (5 min)
  end
  M->>C: GET /v1/services?q=… and /v1/members/{member_ref}/benefits
  C-->>M: services, benefit rows
  M-->>B: services + card_ref (service-options card)
  B->>M: check_benefits(session_ref, svc_focused_skin_exam)
  M->>C: GET /v1/members/{member_ref}/benefits?service_ref=…
  C-->>M: copay $40, referral required, no prior auth
  M->>M: build benefit-coverage card data, store under card_ref (bound to session)
  M-->>B: benefits + card_ref
  opt plan wording needed
    B->>S: semantic query on healthgen-plan-docs
    S-->>B: EOC passages
  end
  B-->>T: reply envelope {reply, card_ref, result_chip, suggestions…}
  T-->>G: same envelope (unchanged)
  G-->>R: Responses API output
  R->>R: parse envelope (fallback: plain text or card_ref from mcp_call output)
  R->>M: GET /internal/cards/{card_ref}?session_ref=… (relay credential)
  M-->>R: {template_id: benefit-coverage@1, data}
  R->>R: template on the allowlist? bind template, mask reply text
  R-->>DL: message (reply + resultChip) · message (Adaptive Card) · message (follow-up + suggestedActions)
  DL-->>W: render bubbles, card, chips
```

<sub>Rendered image for wikis and slides: [images/02-benefit-check.svg](images/02-benefit-check.svg)</sub>

**What the model never sees:** member ids, names from the portal, or card data it did not get from a tool. The model only passes `session_ref` and `card_ref` along.

**Locally:** `foundry-local` does the gateway checks itself and routes with rules instead of an LLM, but it calls the real MCP server, which calls the real broker and the core mock. The cards and data are therefore the same as in Azure.

---

## 3. Pressing a card button

Card buttons arrive as `Action.Execute` with a `verb` and `data`. The relay decides what the model may see.

```mermaid
sequenceDiagram
  autonumber
  participant W as Widget
  participant R as Agent relay
  participant T as Triage → Benefit-check<br/>[local: scripted router]
  participant M as MCP data spoke
  participant C as Core [mock]

  W->>R: message value.action {verb:"providers.search", data:{serviceRef, zip, distance, officeNote?…}}
  alt navigation verb (provider.view, service.details, plan.details)
    R->>R: build route from allow-listed refs (e.g. /providers/prv_19)
    R-->>W: event navigate {route} + short message
    Note over W: widget checks allowedRoutes, then emits a navigate DOM event to the portal router
  else agent verb (service.find, providers.search, appointment.availability, appointment.review, referral.review)
    R->>R: keep only allow-listed keys with valid shapes<br/>(service_ref, provider_ref, slot_ref, zip, radius_miles…)<br/>drop free text such as officeNote
    R-->>W: typing "Searching in-network doctors…"
    R->>T: "The user pressed “Find doctors” (providers.search) in the card with service_ref=…, zip=…, radius_miles=5."
    T->>M: find_providers(session_ref, service_ref, zip, radius_miles)
    M->>C: GET /v1/providers?service_ref&plan_ref&zip&radius_miles
    C-->>M: in-network providers, nearest first
    M-->>T: providers + card_ref (provider-results card, audience = member/provider)
    T-->>R: envelope with card_ref
    R-->>W: reply + provider-results card + follow-up
  else unknown verb
    R-->>W: "That option isn't available any more…" (no agent call)
  end
```

<sub>Rendered image for wikis and slides: [images/03-card-button.svg](images/03-card-button.svg)</sub>

---

## 4. Booking with human confirmation

The model can prepare a booking but cannot make one. Only a Confirm press, recorded by the broker and checked again by the core, unlocks the write.

```mermaid
sequenceDiagram
  autonumber
  participant U as Member (widget)
  participant R as Agent relay
  participant A as Benefit-check agent<br/>[local: scripted router]
  participant M as MCP data spoke
  participant IB as Identity broker
  participant C as Core [mock]

  U->>R: "Review booking" (appointment.review) provider_ref, slot_ref, service_ref
  R->>A: card action sentence
  A->>M: prepare_appointment_request(session_ref, provider_ref, slot_ref, service_ref)
  M->>C: re-check slot is open and service is covered
  M->>IB: POST /v1/actions {kind: appointment.request, params, summary}
  IB->>IB: member_ref set from the session (not the model), role = member?<br/>cancel older pending booking actions, store pending (15 min)
  IB-->>M: action_id act_…
  M-->>A: action_id + card_ref (booking-review, actionId inside)
  A-->>R: envelope "Check the details, then confirm"
  R-->>U: review card "Nothing is booked until you confirm"

  opt model tries to book early
    A->>M: submit_appointment_request(session_ref, act_…)
    M->>IB: token exchange with action_id
    IB-->>M: 400 confirmation_required
    M-->>A: tool error, so it must wait for the user
  end

  U->>R: Confirm booking (verb appointment.confirm, actionId, officeNote)
  rect rgb(255,248,225)
    R->>IB: GET /v1/actions/{act}?session_ref → pending, right kind, not expired?
    R->>IB: POST /v1/actions/{act}/confirm {session_ref, extras:{note}}
    IB->>IB: pending → confirmed (atomic)
  end
  R->>A: "The user confirmed request act_… Call submit_appointment_request with action_id act_…"
  A->>M: submit_appointment_request(session_ref, act_…)
  rect rgb(255,248,225)
    M->>IB: POST /oauth2/token with action_id
    IB->>IB: confirmed → consumed (atomic, once)
    IB-->>M: write JWT: scope appointment.request,<br/>confirmed_action {id, kind, params_sha256} + action params & note
    M->>C: POST /v1/appointments/requests (params from the broker, not the model)
    C->>C: hash(params) == params_sha256? jti not used before? member matches?
  end
  C-->>M: 201 {ref: APT-…, status: booked}
  M-->>A: appointment + card_ref (confirmation card)
  A-->>R: envelope "You're booked."
  R-->>U: confirmation card

  U->>R: Confirm again (same actionId)
  R->>IB: GET action → status consumed
  R-->>U: "This request was already handled…" (no agent call)
```

<sub>Rendered image for wikis and slides: [images/04-booking-hitl.svg](images/04-booking-hitl.svg)</sub>

**In production** the HealthGen core does the checks in the last shaded block. The checks are part of the API contract the MCP server relies on (`services/healthgen-core-mock/README.md`).

---

## 5. Provider referral

This is the same two-step pattern in the provider portal. It adds a provider-panel check and a medical-necessity attestation.

```mermaid
sequenceDiagram
  autonumber
  participant P as Provider staff (widget, provider portal)
  participant BFF as Provider portal BFF<br/>[local: portal-dev]
  participant IB as Identity broker
  participant R as Agent relay
  participant A as Benefit-check agent
  participant M as MCP data spoke
  participant C as Core [mock]

  BFF->>IB: assertion sub=prv_pcp_01, role=provider, member_ref=mbr_7f3a (patient in context)
  Note over BFF,IB: the portal checks the provider-patient relationship before asserting it
  P->>R: "Find a dermatologist for Alex"
  R->>A: turn (portal: provider)
  A->>M: find_providers(session_ref, …)
  M-->>A: card_ref (provider-results, audience provider → "Review referral")
  P->>R: Review referral (referral.review, providerRef=prv_42, serviceRef)
  A->>M: prepare_referral(session_ref, to_provider_ref, service_ref, visits)
  M->>IB: POST /v1/actions {kind: referral.submit} (role must be provider)
  M-->>A: card_ref (referral-review with actionId)
  P->>R: Submit referral (attest = "false")
  R-->>P: "Please confirm medical necessity…" (nothing confirmed)
  P->>R: Submit referral (attest = "true", clinicalNote)
  R->>IB: confirm {extras: {reason: clinicalNote}}
  R->>A: "…Call submit_referral with action_id …"
  A->>M: submit_referral(session_ref, act_…)
  M->>IB: token exchange with action_id → write JWT
  M->>C: POST /v1/referrals
  C->>C: provider token? patient on this provider's panel? confirmation matches?
  C-->>M: REF-… submitted, valid 90 days
  M-->>A: card_ref (confirmation)
  R-->>P: "Referral submitted" card
```

<sub>Rendered image for wikis and slides: [images/05-provider-referral.svg](images/05-provider-referral.svg)</sub>

---

## 6. Hand-off to a care specialist

```mermaid
sequenceDiagram
  autonumber
  participant W as Widget
  participant R as Agent relay
  participant T as Triage agent<br/>[local: scripted router]
  participant M as MCP data spoke
  participant N as n8n workflow<br/>[local: stub route in foundry-local]
  participant CT as Care team (Teams/Slack) / CRM

  W->>R: event handoffRequest ("Talk to a person")<br/>or a message asking for a human
  R-->>W: typing "Connecting you with a care specialist…"
  R->>T: "The user pressed 'Talk to a person'. Hand the conversation to a human care specialist now."
  T->>M: request_human_handoff(session_ref, reason, topic)
  M->>M: payload {session_ref, audience, reason, topic}: no member ids
  M->>N: POST webhook, X-HealthGen-Timestamp + X-HealthGen-Signature (HMAC-SHA256)
  N->>N: verify signature and 5-minute window, clean up fields
  N->>N: create ticket (replace with the CRM create-case call)
  N->>CT: notify the queue (care-team or provider-services)
  N-->>M: {ticket_ref: HO-…, queue, expected_response}
  M-->>T: ticket
  T-->>R: envelope with handoff {ticket_ref, reason}
  R-->>W: event handoff {reason, ticketRef} + message
  Note over W: the portal can open its contact-centre panel from the handoff DOM event
```

<sub>Rendered image for wikis and slides: [images/06-handoff.svg](images/06-handoff.svg)</sub>

---

## 7. Resume, token refresh and logout

```mermaid
sequenceDiagram
  autonumber
  participant W as Widget
  participant BFF as Portal BFF [local: portal-dev]
  participant IB as Identity broker
  participant DL as Direct Line [local: dev_server.py]
  participant R as Agent relay
  participant G as APIM [local: foundry-local]

  Note over W,DL: Token refresh (before expiry)
  W->>DL: POST /v3/directline/tokens/refresh
  alt Direct Line refresh works
    DL-->>W: new token
  else it fails
    W->>BFF: POST token {reason:"refresh", conversationId}
    BFF->>IB: assertion + body
    IB->>IB: binding for this conversation, same user and member, still live?
    IB->>DL: GET /v3/directline/conversations/{id} (secret)
    DL-->>IB: fresh token, streamUrl
    IB-->>W: token for the same conversation and same dl_ user
  end

  Note over W,IB: Page reload (resume)
  W->>BFF: POST token {reason:"resume", conversationId}
  BFF->>IB: assertion
  alt same user and member in context
    IB-->>W: token for the existing conversation (history kept)
  else another member in context, or session ended
    IB-->>W: new conversation and new binding
  end

  Note over W,G: Logout
  BFF->>IB: POST /v1/directline/logout (assertion with idm_session)
  IB->>IB: revoke bindings of that IdM session, cancel pending actions
  W->>R: (late message from an old tab)
  R->>IB: resolve (if not cached) → 401 session_inactive
  R-->>W: "Your session has ended. Refresh the page…"
  Note over R,G: if the relay still has the session cached (up to ~9 min),<br/>APIM's status check (60 s cache) rejects the agent call,<br/>and any MCP token exchange fails at once
```

<sub>Rendered image for wikis and slides: [images/07-resume-refresh-logout.svg](images/07-resume-refresh-logout.svg)</sub>

---

## 8. Failures and guardrails

```mermaid
sequenceDiagram
  autonumber
  participant W as Widget
  participant R as Agent relay
  participant G as APIM [local: foundry-local]
  participant A as Agents [local: scripted router]
  participant M as MCP
  participant IB as Broker

  alt too many turns (more than 20 a minute per conversation)
    W->>R: message
    R-->>W: "You're sending messages quickly…" (no agent call)
  else message over 2,000 characters, or a file attached
    W->>R: message
    R-->>W: short explanation (no agent call)
  else gateway refuses (403: policy, guardrail, content safety)
    R->>G: responses
    G-->>R: 403
    R-->>W: "I can't help with that here…" + Check benefits / Find a doctor
  else agent or gateway error (5xx, timeout after retries for 429/502/503/504)
    R->>G: responses (retried up to 2 times, honouring Retry-After)
    G-->>R: error
    R-->>W: "Sorry, something went wrong…" + Try again / Talk to a person
  else a tool fails
    A->>M: tools/call
    M->>IB: exchange
    IB-->>M: invalid_grant / confirmation_required / …
    M-->>A: tool error "code: friendly text"
    A-->>R: envelope explaining what to do next
  else the agent ignores the envelope format
    A-->>R: plain text
    R->>R: show it as the reply (masked), no card unless an mcp_call output had a card_ref
  else a card_ref from another session, or an unknown template
    R->>M: GET /internal/cards/{ref}?session_ref
    M-->>R: 404 (or template not on the allowlist)
    R-->>W: reply without a card
  end
```

<sub>Rendered image for wikis and slides: [images/08-failures-guardrails.svg](images/08-failures-guardrails.svg)</sub>

---

## 9. Deploying agents and plan documents

```mermaid
sequenceDiagram
  autonumber
  actor Op as Operator (az login)
  participant DA as agents/deploy_agents.py
  participant ARM as Azure Resource Manager
  participant F as Foundry project<br/>(Agent Service, api-version v1)
  participant IG as search/ingest.py
  participant S as Azure AI Search

  Op->>IG: python search/ingest.py
  IG->>IG: split documents/*.md into one chunk per "# section"
  IG->>S: PUT /indexes/healthgen-plan-docs (semantic config)
  IG->>S: POST /docs/index (mergeOrUpload)

  Op->>DA: python agents/deploy_agents.py --env-file foundry.env [--dry-run]
  DA->>DA: load YAML, fill ${VAR}, ${conn:NAME}, {{> envelope}}, refuse leftovers
  loop connections.yaml (search, MCP, 2 × RemoteA2A)
    DA->>ARM: PUT …/projects/{p}/connections/{name}
  end
  loop plan-faq, benefit-check, triage
    DA->>F: GET /agents/{name}
    alt new
      DA->>F: POST /agents {name, definition, description, metadata}
    else exists
      DA->>F: POST /agents/{name}/versions {definition…}
    end
    opt a2a.enabled (the specialists)
      DA->>F: PATCH /agents/{name} (merge-patch: protocol a2a + agent_card) ⚠ verify body
      DA->>F: GET /agents/{name}/endpoint/protocols/a2a/agentCard/v1.0
    end
  end
  DA-->>Op: next: grant the triage identity "Foundry Agent Consumer"
```

<sub>Rendered image for wikis and slides: [images/09-deploy-agents.svg](images/09-deploy-agents.svg)</sub>

---

## 10. Local stack and automated tests

This shows how the stand-ins replace Azure on a laptop, and what each test suite actually exercises.

```mermaid
sequenceDiagram
  autonumber
  participant E2E as tests/e2e/test_local_stack.py<br/>(plays the widget)
  participant LS as scripts/local_stack.py
  participant P as portal-dev :9080
  participant DL as dev_server.py :9104<br/>(Direct Line emulator + relay core)
  participant FL as foundry-local :9105<br/>(gateway checks + scripted agents + hand-off stub)
  participant IB as identity-broker :9102
  participant M as mcp-healthgen :9103
  participant C as core-mock :9101

  E2E->>LS: running(base=9100)
  LS->>LS: start 6 uvicorn processes with dev keys and wait for /healthz
  E2E->>P: GET /?user=alex (cookie), POST /api/agent/directline-token
  P->>IB: portal assertion → token
  IB->>DL: tokens/generate (secret)
  E2E->>DL: POST conversations, POST activities (spoofed from.id is overwritten)
  DL->>DL: relay core in-process
  DL->>IB: resolve session
  DL->>FL: conversations / responses (key + X-User-Context)
  FL->>IB: JWKS (validate user context)
  FL->>M: MCP tools (key)
  M->>IB: token exchange
  M->>C: core APIs (downstream JWT)
  E2E->>DL: GET activities?watermark (poll like the widget)
  Note over E2E: asserts cards, verbs, HITL, role checks, hand-off, token binding
```

<sub>Rendered image for wikis and slides: [images/10-local-stack-tests.svg](images/10-local-stack-tests.svg)</sub>

| Test suite | Real | Stand-in or fake |
| --- | --- | --- |
| `services/healthgen-core-mock/tests` | Core mock over HTTP | Test RSA key acting as the broker |
| `services/identity-broker/tests` | Broker over HTTP, SQLite, Key Vault REST shape | Fake Direct Line, fake Key Vault, test portal key |
| `services/mcp-healthgen/tests` | MCP client and server, broker, core mock | Fake Direct Line, fake n8n |
| `services/agent-relay/tests` | Relay core, templates, envelope | In-process fakes for broker, cards and Foundry |
| `tests/e2e` | All six processes over HTTP | portal-dev, the Direct Line emulator and foundry-local, instead of Azure |
