# `clients/portal-dev-agui/index.html`

Source: [`clients/portal-dev-agui/index.html`](../../../../../clients/portal-dev-agui/index.html)

> **Summary:** Host page for the AG-UI local run. It is the `portal-dev` page with one change: `widget.init` injects `AgentWidget.AgUiTransport` instead of using Direct Line.

| | |
| --- | --- |
| Layer | Portal stand-in |
| Local run | Served by `server.py` at http://localhost:8081 |

It also turns on `features.history`, so a reload resumes the thread from `GET /agui/threads/{id}`. The journey buttons call `widget.startJourney`, which the transport sends as `forwardedProps.journey`.
