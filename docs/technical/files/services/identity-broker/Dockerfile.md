# `services/identity-broker/Dockerfile`

Source: [`services/identity-broker/Dockerfile`](../../../../../services/identity-broker/Dockerfile)

> **Summary:** The container image of the identity broker: `python:3.13-slim`, the pinned requirements and `app/`, run as UID 10001 with `uvicorn app.main:app --port 8102 --proxy-headers`.

Deploy it on **internal** ingress with one replica (pilot) and the `id-broker` managed identity (runbook step 5). `BROKER_DB_PATH=/tmp/broker.db` is ephemeral by design: see [`app/store.py`](app/store.py.md) for the scale-out path.
