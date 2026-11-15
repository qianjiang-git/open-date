# Hosting the Vexo Match demo on Render

Status: **prepared, not deployed.** The deployment configuration exists and validates
locally. No Render resources have been created, and the pasted management API key was not
used or stored anywhere.

## What runs where

```text
Laptop A hub + phone page ---- HTTPS ----+
                                        +-- Render web service -- Render Postgres
Laptop B hub + phone page ---- HTTPS ----+

Band A <-- Bluetooth --> Laptop A
Band B <-- Bluetooth --> Laptop B
```

- One free Render **Python web service** serves the phone UI and `/api/*` on one origin.
- One free Render **Postgres** database stores users, matches, sightings, leases and jobs.
- Bluetooth stays on each laptop. Hubs poll the deployed service over outbound HTTPS with
  their own hub token. Browsers use relative API URLs, so no origin configuration is needed.
- The free web service has an ephemeral filesystem. SQLite files and local uploads are not
  durable there, which is why hosted state moved to Postgres.

## Files added for hosting

| File | Purpose |
| --- | --- |
| `render.yaml` | Blueprint: one free web service + one free Postgres in Oregon |
| `requirements.txt` | Hosted runtime dependencies (no Bluetooth SDK) |
| `requirements-dev.txt` | Adds pytest/httpx for local validation |
| `server/asgi.py` | Hosted entry point: backend selection, env overrides, health checks |
| `server/pg.py` | PostgreSQL backend with serialized writes and guarded migrations |
| `.env.example` | Local environment template; contains no secrets |
| `scripts/smoke.py` | Post-deploy health/readiness/UI checks |
| `tests/test_pg_compat.py` | SQL translation and readiness tests (no database required) |

Application files remain owned by the application agent. `server/db.py` is untouched; the
hosted entry point selects Postgres through `server/pg.py`, so local SQLite tests keep
working.

## Security: rotate the API key that was pasted into chat

The Render management key was exposed in conversation. Revoke it and create a new one in
Render (**Account Settings -> API Keys**) before deploying. It is not an application login
and is not needed by the running service. Never put it in `render.yaml`, `.env.example`,
source, logs, hub config, or the phone page. Deployment should read it from the deployer's
environment only, or use the Render dashboard/Blueprint flow.

## Local validation

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -c "import server.asgi"
.venv/bin/pytest -q tests/test_pg_compat.py
```

To exercise Postgres locally, start a disposable Postgres and point the app at it:

```sh
export DATABASE_URL=postgresql://vexo:vexo@localhost:5432/vexo
.venv/bin/python -c "from server.pg import open_database; db = open_database(); print(type(db).__name__); print(db.one('SELECT version FROM schema_version'))"
```

Without `DATABASE_URL` the same command returns the SQLite backend, which is what local
tests use.

## Deploy with the Blueprint

1. Finish the application and UI, then commit and push the intended revision to `main`.
   This is a prerequisite: Render deploys a Git revision, not the local working tree.
2. In Render choose **New -> Blueprint**, connect the repository, and select `main`.
3. Review the plan: exactly one **Free** web service and one **Free** Postgres, both in
   Oregon. Do not add paid disks, workers, cron jobs or instances.
4. Create the resources. `DATABASE_URL` is wired automatically from the database's internal
   connection string; the service does not need the external connection string.
5. Wait for `/readyz` to return 200, then run:

   ```sh
   python scripts/smoke.py https://<service>.onrender.com
   ```

6. Seed demo users through the application's operator/enrollment path. Do not seed on every
   startup; restarts must not overwrite real data.
7. Configure each laptop hub with `SERVER_URL=https://<service>.onrender.com` and its own hub
   token. Never share user or operator tokens with a hub.
8. Rehearse with simulated observations first. Before the event, set `VEXO_DEMO_MODE=real`
   in the Render dashboard and restart, so physical band observations are accepted.
9. Restart once and confirm data survives and old lighting does not resume.

If the repository is private, an API key alone does not grant Render Git access; authorize
the GitHub repository in Render first. The Blueprint is the supported path; creating the
same resources through the API is equivalent but requires the repository to be deployable.

## Environment contract

| Variable | Where | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Web service | Set by the Blueprint from the database reference |
| `APP_ENV` | Web service | Informational: `hosted` |
| `VEXO_DEMO_MODE` | Web service | `real`, `single_laptop`, or `simulated` |
| `SCORER_PROVIDER` | Web service | `deterministic` first; `claude` only after a live check |
| `ANTHROPIC_API_KEY` | Web service | Optional, server-side only, set in the dashboard |
| `ANTHROPIC_MODEL` | Web service | Exact available model ID; never guessed |
| `VEXO_ROSTER` | Web service | Optional comma-separated authorized band numbers |
| `CORS_ORIGINS` | Web service | Optional exact origins for a separate frontend or Replit preview |
| `SERVER_URL` | Each laptop hub | Public HTTPS origin; not a server secret |

`DEMO_MODE` is accepted as an alias for `VEXO_DEMO_MODE`. Free-tier behavior to plan for:
the web service sleeps after about 15 minutes without traffic and may take about a minute
to wake; free Postgres expires after 30 days and has no backups. Export anything worth
keeping before expiry. Free services cannot use persistent disks or paid pre-deploy
commands, so migrations run in a guarded startup step.

## Frontend build and CORS

The final phone UI is expected to be a static build served by this same FastAPI service.
Commit the built output under `ui/` (or add a reliable build step), because the Render
Python runtime does not guarantee a Node toolchain. Same-origin production needs no CORS
configuration.

A Replit preview or any separate frontend origin must be added explicitly, for example
`CORS_ORIGINS=https://<preview>.replit.dev,http://localhost:5173` in the Render dashboard.
The backend allows exactly those origins plus the `Authorization` and `Content-Type`
headers and the API methods; it never uses a wildcard. Use the deployed same-origin build
for the event rather than depending on a preview origin.

## What is still blocking a live deployment

- `ui/` is still empty, so `/` will be 404 until the application agent adds `phone.html`
  and `operator.html`.
- Application tests are still being written; run the full suite when the app agent is done.
- Nothing is committed or pushed yet. I did not commit another agent's in-progress work.
- The exposed API key must be rotated.
- No Render resource has been created or verified live.

## Health checks

- `/healthz` is process liveness only and always returns 200 without touching the database
  or any LLM provider.
- `/readyz` checks database connectivity and that the schema version is current. It returns
  503 with a sanitized reason when the database is unavailable or still migrating.
- Render uses `/readyz` as the service health check. `/healthz` is available for a shallow
  external ping.

## Postgres correctness notes

- `server/pg.py` preserves the repository's single-writer transaction contract with a
  transaction-scoped PostgreSQL advisory lock, which works across restarts and overlapping
  deployments rather than only inside one process.
- Startup migrations take a separate session advisory lock, so two instances cannot migrate
  concurrently. Schema changes are versioned and transactional.
- Timestamps use `DOUBLE PRECISION`, not SQLite's 4-byte `REAL`, so epoch seconds keep their
  precision.
- `INSERT OR IGNORE` becomes `ON CONFLICT DO NOTHING`; the one `MAX(a, b)` upsert becomes
  `GREATEST(a, b)`.
- Existing job leases, match deadlines, cooldowns and cleanup commands are stored in
  Postgres, so restart reconciliation can expire stale work instead of resuming old lights.
