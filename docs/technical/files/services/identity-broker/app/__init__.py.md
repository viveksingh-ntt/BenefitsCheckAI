# `services/identity-broker/app/__init__.py`

Source: [`services/identity-broker/app/__init__.py`](../../../../../../services/identity-broker/app/__init__.py)

> **Summary:** An empty file that makes `app/` a Python package (`uvicorn app.main:app`, relative imports between modules).

Keep it free of side effects. `app.main` builds the ASGI app lazily, so importing it (in tests, for example) needs no environment variables.
