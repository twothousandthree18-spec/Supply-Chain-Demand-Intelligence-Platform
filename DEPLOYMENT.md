# Deployment

How to run the Supply Chain & Demand Intelligence Platform in production. The web/API
service is a stateless FastAPI application that reads from a PostgreSQL warehouse. Static
frontend assets are served by the app itself, so a single process exposes the whole product.

---

## 1. Environment variables

All settings are environment-driven (no secrets in source; `settings.py` + `src/etl/db_utils.py`).
Copy `.env.example` to `.env` and set real values, or export them in the shell.

| Variable | Default | Purpose |
|---|---|---|
| `PGHOST` | `127.0.0.1` | PostgreSQL host |
| `PGPORT` | `5432` | PostgreSQL port |
| `PGDATABASE` | `supply_chain_intelligence` | Database name |
| `PGUSER` | `postgres` | Database user |
| `PGPASSWORD` | *(unset — trust auth)* | Database password (only if the server requires it) |
| `KAGGLE_USERNAME` / `KAGGLE_KEY` | *(unset)* | Required **only** to re-acquire the M5 source data via `scripts/acquire_m5.py` |

The only external service required is PostgreSQL itself. `PGPASSWORD` is optional and is read
at runtime; it is never written into source.

---

## 2. Local production-start command

Activate the virtualenv, then run uvicorn directly against the module app object:

```powershell
# Windows (PowerShell)
.venv\Scripts\python.exe -m uvicorn src.web.main:app --host 0.0.0.0 --port 8000

# Linux/macOS / bash
.venv/bin/python -m uvicorn src.web.main:app --host 0.0.0.0 --port 8000
```

Replace `--port 8000` with your desired port. For higher concurrency add `--workers N`
(e.g. `--workers 4`) — the app is read-only and connection-pools via psycopg2.

Verify the service:

```text
GET /           -> 200 Index (SPA shell)
GET /healthz    -> 200 {"status":"ok"}
GET /api/docs   -> 200 OpenAPI/Swagger UI
```

---

## 3. Docker (recommended for self-hosting)

Two artifacts are provided: **`Dockerfile`** (web/API image) and **`docker-compose.yml`**
(app + PostgreSQL storage behind a health-checked dependency).

```bash
# Full stack (PostgreSQL + web/API)
cp .env.example .env          # set PGPASSWORD in the environment if you want one
docker compose up --build
open http://localhost:8000
```

```bash
# Web/API image only (point it at an existing PostgreSQL by setting PGHOST/PGPORT/...)
docker build -t supply-chain-intelligence .
docker run -p 8000:8000 \
  -e PGHOST=db.example.com -e PGPORT=5432 \
  -e PGDATABASE=supply_chain_intelligence -e PGUSER=postgres -e PGPASSWORD=... \
  supply-chain-intelligence
```

> The compose `db` service starts empty. Restore an existing warehouse (a logical dump of the
> `supply_chain_intelligence` database) into it, or run the Phase 2 ETL
> (`python -m src.etl.build_warehouse`) against it before browsing.

---

## 4. Reverse proxy (optional, for a public host)

Terminate TLS and proxy `/` to uvicorn. Static caching can be applied to `/static/*`. Example
Caddy:

```text
example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Or Nginx:

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
}
```

---

## 5. Notes on scope

- **No public deployment exists in this repository.** Docker/config files are provided so the
  project can be stood up on any host (VPS, Cloud Run, Railway, Render, etc.) with PostgreSQL.
- The application is **read-only** at the data layer: it never runs ETL/DML/DDL, so it is safe
  behind a read-only database role if desired.
- Simulated figures (forecast, inventory, risk) are always labelled as such in the UI; the web
  layer never reads `fact_daily_sales` directly and loads no bulk 59M-row tables — every
  endpoint is paginated/filtered/bounded.