# `services/healthgen-core-mock/Dockerfile`

Source: [`services/healthgen-core-mock/Dockerfile`](../../../../../services/healthgen-core-mock/Dockerfile)

> **Summary:** The container image of the core mock: `python:3.13-slim`, run as UID 10001 with `uvicorn app.main:app --port 8101`.

For the pilot it is deployed on internal ingress with one replica. Retire it when the real core is connected.
