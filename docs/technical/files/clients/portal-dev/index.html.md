# `clients/portal-dev/index.html`

Source: [`clients/portal-dev/index.html`](../../../../../clients/portal-dev/index.html)

> **Summary:** The local host page. It shows how a portal embeds `<agent-widget>` against the real stack, with a user switcher, three journey buttons and an event log.

## What it does

- `server.py` replaces `__CONFIG__` with the user, portal, display context and Direct Line domain.
- It sets the widget's `portal` and `theme` attributes and calls `widget.init({...})` with:
  - `tokenUrl: '/api/agent/directline-token'`;
  - `directLineDomain` pointing at the local emulator, and `webSocket: false` (the emulator polls);
  - `context` (display only), `allowedRoutes`, `features`, `welcome.suggestions` and `telemetry.sessionId`.
- It logs the `navigate`, `handoff`, `action`, `error` and `tokenExpired` DOM events.
- Its journey buttons call `widget.startJourney('benefit-check' | 'service-search' | 'doctor-search', params)`.

## How it's used in the real system

It shows the integration points a real portal page needs:

- `tokenUrl`, `context` and `allowedRoutes`;
- routing `navigate` events into the portal router, and opening the contact centre on `handoff`;
- starting journeys from portal buttons.

In Azure, drop `directLineDomain` and `webSocket` (the defaults use Direct Line with WebSockets), or set a regional domain.
