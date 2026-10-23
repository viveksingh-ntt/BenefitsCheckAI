# Agentic Client Widget (`<agent-widget>`)

An embeddable, agent-agnostic chat Web Component for the member and provider portals. It talks
**Direct Line** to the **Agent relay** (M365 Agents SDK), renders the **Adaptive Cards** the relay
builds, and exposes a small host API so any portal page can configure it, pass context and react
to what the agent asks for.

It sits in the *Portal and channel* lane of the target architecture:

```
Portal page ──host API──▶ <agent-widget> ──Direct Line──▶ Agent relay ──▶ APIM ──A2A──▶ Triage / Benefit / FAQ agents ──▶ MCP data spoke
   ▲                          │
   └──── DOM events ──────────┘  (navigate, handoff, action, tokenExpired, error)
```

- Zero framework dependencies: a native custom element with Shadow DOM, so it works in React,
  Angular, .NET MVC or a CMS page.
- Runtime dependencies: `marked` and `DOMPurify` only (agent markdown is always sanitized).
- CDN bundle: about 139 KB minified, 44 KB gzipped.

## Quick start

### CDN (any portal)

```html
<script src="https://cdn.yourorg.com/agent-widget/v0/agent-widget.iife.js" integrity="sha384-…" crossorigin="anonymous"></script>

<agent-widget agent-id="care-assistant" portal="member" mode="docked" theme="member-portal" locale="en-US"></agent-widget>

<script>
  const widget = document.querySelector('agent-widget');
  widget.init({
    tokenUrl: '/api/agent/directline-token',          // portal backend; never a Direct Line secret in the browser
    context: {
      member: { ref: 'mbr_7f3a', displayName: 'Alex Morgan', planName: 'Harbor HMO', idLast4: '4821', status: 'Active', relationship: 'self' },
      page: { route: '/benefits', breadcrumb: 'Benefit check' },
    },
    allowedRoutes: ['/plan/*', '/care/*', '/providers/*'],
    features: { suggestions: true, handoff: true, feedback: true },
  });

  widget.addEventListener('navigate', (e) => router.push(e.detail.route));
  widget.addEventListener('handoff', (e) => contactCenter.open(e.detail.ticketRef));
  widget.addEventListener('tokenExpired', () => session.refresh());

  // From any portal button:
  // widget.startJourney('doctor-search', { serviceCode: 'derm-skin-exam', zip: '10012', radiusMiles: 5 });
</script>
```

### npm (bundled portals)

```ts
import '@yourorg/agent-widget';                 // registers <agent-widget>
import type { AgentWidgetElement } from '@yourorg/agent-widget';

const widget = document.querySelector('agent-widget') as AgentWidgetElement;
widget.init({ getToken: async (req) => (await fetch('/api/agent/directline-token', { method: 'POST', body: JSON.stringify(req), credentials: 'include' })).json() });
```

## Host API

### Attributes

| Attribute | Values | Purpose |
| --- | --- | --- |
| `agent-id` | registry id, e.g. `care-assistant` | Which agent (sent to the relay with context) |
| `portal` | `member` · `provider` | Audience: context-header wording, action sets chosen by the relay |
| `mode` | `launcher` (default) · `docked` · `inline` · `fullpage` | Layout. Launcher and docked go full-screen on phones |
| `position` | `bottom-right` · `bottom-left` | Launcher placement |
| `theme` | preset id | Theme preset (tokens can also be passed in `init`) |
| `locale` | BCP-47, e.g. `en-US`, `es-US` | UI strings and date formatting |
| `environment` | `prod` · `test` · `demo` | Shows "Illustrative data" outside production |
| `open` | boolean | Panel open (launcher/docked) |

### `init(options)`

| Option | Purpose |
| --- | --- |
| `getToken(request)` | Returns `{ token, conversationId?, expires_in?, userId? }` from the portal backend. Called with `reason: 'start'` for a new conversation and `'resume'` (with `conversationId`) to reconnect. Routine refresh uses Direct Line's own `/tokens/refresh`; `getToken({ reason: 'refresh' })` is only the fallback when that fails, so the backend should handle it by reconnecting server-side (`GET /conversations/{id}` with the secret) |
| `tokenUrl` | Alternative to `getToken`: the widget POSTs `{ reason, conversationId? }` with cookies |
| `directLineDomain`, `webSocket` | Regional/private Direct Line endpoint; polling fallback |
| `context` | Initial member / provider / page context (below) |
| `welcome` | `{ message, suggestions[] }` shown locally before the first turn |
| `features` | `suggestions`, `handoff`, `feedback`, `attachments` (up to 5 files, 10 MB each; needs a transport with upload), `history` (resume via sessionStorage, conversation id only) |
| `allowedRoutes` | Routes the agent may ask the portal to open (`/providers/*`). Anything else is blocked |
| `allowedUrlOrigins` | Origins `Action.OpenUrl` may open (same origin always allowed; https only) |
| `labels` | Title, tagline, placeholder, disclaimer, support link text |
| `theme` | Design tokens (`brand`, `surface`, `text`, …) |
| `telemetry` | `{ sessionId, traceParent, onEvent }` — events carry no PHI; every activity gets a W3C `traceparent` |
| `cardRenderer` | Swap the card renderer (see *Adaptive Cards*) |
| `transport` | Inject a transport or a factory (the mock relay uses this) |

### Context (`init({ context })` / `setContext(partial)`)

```ts
{
  member:   { ref, displayName, planName?, idLast4?, status?, relationship?: 'self' | 'dependent' | 'patient' },
  provider: { npi?, tin?, orgName? },
  page:     { route?, breadcrumb?, entity?: { type, ref } },
  hints:    { [key]: string | number | boolean },   // non-PHI only
}
```

- The member fields render the pinned context header ("Alex Morgan · Your plan" or "Selected member: Alex Morgan").
- **Only references go to the relay** (`member.ref`, `relationship`, provider NPI/TIN, page). Display fields stay in the browser.
- Changing `member.ref` ends the conversation and starts a new one, so answers never mix members.
- Context is a hint. APIM and the policy engine re-verify identity and the member relationship from the token on every call.

### Methods

`init(options)` · `open()` · `close()` · `toggle()` · `setContext(partial)` ·
`startJourney(journeyId, params)` (pass `params.prompt` to show it as the user's message) ·
`sendMessage(text, params?)` · `newThread()` · `destroy()`

Methods never reject. Failures show in the widget and fire an `error` event:

- A message that can't be sent stays in the conversation with **Retry**; the text is never lost.
- A dropped connection shows a banner with **Retry**. Any send also reconnects, resuming the same
  Direct Line conversation where possible.
- If the relay never answers, the "working" indicator clears after 60 seconds.

### Events (`widget.addEventListener(name, handler)`)

| Event | `detail` | Notes |
| --- | --- | --- |
| `ready` | `{ version }` | After `init` |
| `open` / `close` | — | |
| `navigate` | `{ route, params? }` | Only for routes in `allowedRoutes` |
| `action` | `{ verb, refs }` | **Cancelable**: `preventDefault()` to handle a card action in the portal instead of the relay. `refs` holds only `*Id` / `*Ref` values, never free text |
| `handoff` | `{ reason, ticketRef? }` | Relay created a contact-center hand-off |
| `tokenExpired` | — | Token refresh failed; refresh the portal session |
| `error` | `{ code, message }` | `token` · `connection` · `send` · `render` · `config` |

### Theming

Tokens become CSS custom properties on the element, so a portal can also override them from its own stylesheet:

```css
agent-widget { --aw-brand: #0b5cad; --aw-brand-soft: #e6effa; --aw-font: 'Source Sans 3', sans-serif; }
```

## Relay contract (what the Agent relay sends and receives)

All traffic is standard Direct Line activities. The widget reads these conventions:

| Activity | Direction | Widget behaviour |
| --- | --- | --- |
| `message` with `text` (markdown) | relay → widget | Assistant message (sanitized markdown) |
| `typing` + `streaminfo` entity `streamType: 'informative'` | relay → widget | Progress line, e.g. "Checking plan eligibility…" |
| `typing` + `streaminfo` `streamType: 'streaming'`, then `message` with `streamType: 'final'` | relay → widget | Streamed text, replaced by the final message (M365 Agents SDK streaming) |
| `message` + Adaptive Card attachment | relay → widget | Card (`application/vnd.microsoft.card.adaptive`) |
| `message.suggestedActions` | relay → widget | Next-step chips. `channelData.recommended: true` on a `CardAction` highlights it |
| `message.channelData.resultChip` `{ text, state }` | relay → widget | Green check line under the message ("Plan eligibility and benefits reviewed") |
| `message.channelData.breadcrumb` | relay → widget | Breadcrumb strip ("Member · Doctor search") |
| `event` `navigate` `{ route, params }` | relay → widget | Raised to the host if allowlisted |
| `event` `handoff` `{ reason, ticketRef }` | relay → widget | Raised to the host |
| `event` `context` | widget → relay | Context references; sent on connect and on change |
| `event` `startJourney` `{ journeyId, params }` | widget → relay | Deep link without a prompt |
| `event` `handoffRequest`, `feedback` | widget → relay | "Get support" link; thumbs up/down |
| `message` with `value` (no text) | widget → relay | Card action. `Action.Execute` → `value: { action: { type: 'Action.Execute', verb, data } }`; `Action.Submit` → `value: data`. `replyToId` is the card's message id |

Every outgoing activity carries `channelData.clientActivityId`, `channelData.traceparent` and
`channelData.widget { version, portal, agentId }`.

## Adaptive Cards

- **Default renderer:** `LiteCardRenderer`, built in and dependency-free. It supports schema ≤ 1.6
  elements used by the catalogue: TextBlock, RichTextBlock, Image (https only), Container, ColumnSet,
  FactSet, ActionSet, Badge, Input.Text/Number/Date/Time/Toggle/ChoiceSet, Action.Submit/Execute/OpenUrl/
  ToggleVisibility/ShowCard, `fallback`, `isVisible`, `spacing`, `separator`, `selectAction`, input
  validation (`isRequired`, `regex`, `errorMessage`, required toggles).
- **Custom element `Org.SelectableList`:** the rich radio rows from the prototype (doctors, services, time
  slots). Each template gives it a `fallback` to `Input.ChoiceSet` (expanded) for hosts such as Teams.
- **Answered cards:** after a Submit/Execute the card is disabled and shows what was chosen, so earlier
  cards cannot be submitted twice. Add `"keepActive": true` to an action's `data` for non-write actions
  (View doctor, View plan details).
- **Microsoft SDK option:** `createSdkRenderer(AdaptiveCards)` from `@yourorg/agent-widget/sdk-renderer`
  wraps the official `adaptivecards` v3 package and registers the same custom elements:

  ```ts
  import * as AdaptiveCards from 'adaptivecards';
  import { createSdkRenderer } from '@yourorg/agent-widget/sdk-renderer';
  widget.init({ ..., cardRenderer: createSdkRenderer(AdaptiveCards) });
  ```

  > **Not yet verified.** npm was unreachable in the environment that produced this code, so the SDK
  > adapter is type-checked but has not been run. `npm install && npm run test:sdk` renders the real
  > templates through the SDK and checks the custom elements and actions; run it before relying on it.

### Template catalogue (`templates/`)

Relay-side templates (Adaptive Card Templating, `${…}` binding). The relay binds data, masks PHI and
chooses the action set for the audience:

| Template | Screen | Actions |
| --- | --- | --- |
| `benefit-coverage@1` | Member benefit check | Find this service · View plan details |
| `service-options@1` | Member service search | Find doctors · Service details |
| `provider-results@1` | Doctor search (member and provider) | Check availability (member) / Review referral (provider) · View doctor |
| `availability-slots@1` | Appointment times | Review booking · Change doctor |
| `booking-review@1` | Appointment review (HITL) | Confirm booking · Change time |
| `referral-review@1` | Referral review (HITL, required attestation) | Submit referral · Change doctor |
| `confirmation@1` | Confirmation | — |

## Security

- No Direct Line secret or agent credential in the browser: tokens come from the portal backend and are
  refreshed through it.
- Agent text is markdown → sanitized HTML (no raw HTML, scripts, styles or images). Card images must be https.
- Navigation and `Action.OpenUrl` are allowlisted; everything else is blocked and logged to telemetry.
- Host events and telemetry carry ids and verbs only, never free text or member data.
- Context sent to the relay contains references only; identity is enforced by APIM / OPA.
- Nothing is written to browser storage except the conversation id when `features.history` is on.

## Develop

```bash
npm install
npm run build        # dist/ bundles + type declarations
npm test             # unit tests (templating, conversation store, policy, theme, Direct Line client)
npm run test:e2e     # headless Chromium: every prototype journey, failure/retry paths, connection races,
                     # phone + dark mode; screenshots in test/e2e/screens/
npm run test:sdk     # renders the template catalogue through Microsoft's adaptivecards SDK (createSdkRenderer)
npm run demo         # http://localhost:5173/demo/ — playground with the mock relay
```

### Layout

```
src/
  index.ts                 entry; registers <agent-widget>
  types.ts                 public types: host API, events, Direct Line activity subset
  ui/agent-widget.ts       the custom element (host API, rendering, actions, chips, composer)
  ui/styles.ts, theme.ts   Shadow-DOM styles and design tokens
  core/directline.ts       Direct Line 3.0 client (WebSocket, reconnect, token refresh, polling, upload)
  core/conversation.ts     activity stream → chat items (streaming, echo de-dup, chips, breadcrumb)
  core/policy.ts           route / URL allowlists, ref extraction
  core/markdown.ts         sanitized markdown
  core/telemetry.ts        privacy-safe events + W3C traceparent
  core/i18n.ts             en-US, es-US strings
  cards/renderer.ts        renderer contract
  cards/lite/              built-in Adaptive Cards renderer (+ Org.SelectableList)
  cards/sdk-adapter.ts     adapter for Microsoft's adaptivecards SDK (unverified)
  mock/                    mock relay + mini templating engine for demos and tests
templates/                 card template catalogue (for the relay)
demo/                      playground page
test/unit, test/e2e        tests
```

## Open items

- Run `npm run test:sdk` to verify the `adaptivecards` SDK adapter, then decide which renderer ships by default.
- Confirm with the relay team: the `value` shape for `Action.Execute`, streaming support, and the
  `resultChip` / `breadcrumb` channelData conventions.
- Decide whether "Check availability" calls a real scheduling API in v1.
- Accessibility audit with a screen reader (automated checks cover names, roles and keyboard selection only).
