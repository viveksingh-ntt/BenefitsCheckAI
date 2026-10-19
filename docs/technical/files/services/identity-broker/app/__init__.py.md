# `services/identity-broker/app/__init__.py`

Source: [`services/identity-broker/app/__init__.py`](../../../../../../services/identity-broker/app/__init__.py)

> **Summary:** An empty file that makes `app/` a Python package (`uvicorn app.main:app`, relative imports between modules).

There is no package initialization logic here: importing `app` does not load configuration, create the database, or initialize cryptographic keys. `app.main` exposes a lazy ASGI application and initializes its dependencies on the first request.
