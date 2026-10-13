# `clients/portal-dev/vendor/agent-widget.iife.js`

Source: [`clients/portal-dev/vendor/agent-widget.iife.js`](../../../../../../clients/portal-dev/vendor/agent-widget.iife.js)

> **Summary:** A vendored, minified build of the Agentic Client Widget (from the separate `agent-widget` repo, `dist/agent-widget.iife.js`, v0.1.0). It is included so the local stack works without building the widget.

It registers `<agent-widget>` and the global `AgentWidget`. Don't edit it by hand. To test widget changes, build the widget repo (`npm run build`) and set `WIDGET_DIST=../agent-widget/dist`, or copy the new build here.

In production, portals load the widget from your CDN with a subresource integrity hash, or bundle it through npm. This file is for local runs only.
