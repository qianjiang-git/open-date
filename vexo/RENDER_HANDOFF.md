# Vexo Match Render deployment handoff

Deploy the shared matching API and phone web interface on one Render Free Web Service, backed by Render Free Postgres in the same region. Bluetooth hubs stay on participants' laptops and use outbound authenticated HTTPS polling. No direct connection between laptops is required.

This handoff overrides SQLite and local-server deployment choices in `IMPLEMENTATION_PLAN.md` for the hosted environment. Preserve its product flow and hardware limitations. Coordinate changes to database code with the agent implementing the application; do not independently replace files another agent is editing.

## Work split

The application agent owns matching, eligibility, lifecycle, UI, voice, and Bluetooth hubs. The deployment agent owns `render.yaml`, deployment dependency packaging, environment examples, health/readiness integration, deployment documentation, and a proposed Postgres integration patch coordinated with the application agent. Keep radio SDK dependencies out of the hosted server unless actually imported there.

## Target architecture

```text
Laptop A hub + phone page ---- HTTPS ----+
                                        +-- Render Web Service -- Render Postgres
Laptop B hub + phone page ---- HTTPS ----+

Band A <-- Bluetooth --> Laptop A
Band B <-- Bluetooth --> Laptop B
```

The web service serves the static phone interface and `/api/*` from one origin. Browser API calls use relative URLs. Each laptop hub reads a configurable `SERVER_URL=https://<service>.onrender.com` and its own hub token. HTTPS is handled by Render. Do not put database or provider credentials in browsers or hubs.

## Required implementation

1. Inspect the actual application layout and dependency files before selecting commands. Expected ASGI entry point is `server.app:app`; confirm it exists. Use one Uvicorn process, binding `0.0.0.0` and Render's `PORT` environment variable. Do not use development reload.
2. Add `render.yaml` provisioning one free Python web service and one free Postgres database in the same region, preferably Oregon. Set both plans explicitly to free. Disable automatic deploys during the live demo unless deliberately re-enabled. Avoid paid disks, workers, cron jobs, or other paid resources.
3. Set `DATABASE_URL` on the web service using the database's internal `connectionString` reference. Keep database access internal to the application; restrict external access where supported and verify connectivity before disabling anything.
4. Support Postgres through the application's repository layer. Do not treat a Postgres URL as a SQLite filename. Use migrations and a PostgreSQL driver. Keep SQLite optional for local tests only if doing so remains simple; validate critical database behavior against Postgres too.
5. Replace SQLite-specific SQL, types, placeholders, migrations, and `BEGIN IMMEDIATE`. For pair allocation, lock the two participant rows in canonical ID order within a transaction, re-read eligibility, and atomically insert both active-member reservations. Retain unique member/color constraints and handle conflicts by rolling back the entire transaction. Do not rely on process-local locks as the only safeguard.
6. Apply versioned migrations through a guarded startup step before accepting requests, since free services do not provide paid pre-deploy commands. Protect migrations with a database advisory lock so overlapping deployments cannot run them concurrently. Use idempotent migration versions and backward-compatible schema changes.
7. Run deadline/scoring/reconciliation tasks inside the web application lifespan. Use database job leases/locking to tolerate deploy overlap and restart; one Uvicorn worker is not a substitute for transactional correctness. No separate paid worker is needed for the demo.
8. Add `/healthz` for process health and `/readyz` for database connectivity and schema readiness. Both return sanitized results. Use readiness as the Render health check if it completes quickly; return a failure status when the database is unavailable. Do not contact the LLM provider in a health check.
9. Keep demo seed execution explicit and idempotent. Do not reset or overwrite existing users, matches, tokens, or preferences at every startup. Seeding must be executable without an interactive Render shell, for example through an operator-authenticated, demo-only action.
10. Persist notifications, profiles, ownership, commands, leases, and jobs in Postgres. Treat local files as temporary. Restart reconciliation expires stale sightings, jobs, matches, and lighting leases before resuming matching. Never replay an old color merely because it was stored before restart.
11. Add tests for Postgres member allocation, duplicate ticks, pause-versus-scoring races, migrations, and restart recovery. Add basic deployed smoke checks after resource creation.

## Environment contract

The names below are proposed; reconcile them with the actual application configuration rather than introducing competing names.

| Variable | Location and purpose |
| --- | --- |
| `DATABASE_URL` | Web service only; database reference from Render |
| `APP_ENV` | Web service; hosted/demo behavior |
| `DEMO_MODE` | Explicitly enable seeded demo and operator routes |
| `SCORER_PROVIDER` | Start with deterministic scoring; Claude optional |
| `ANTHROPIC_API_KEY` | Server-side Render secret, only if Claude is enabled |
| `ANTHROPIC_MODEL` | Verified available model ID, no guessed identifiers |
| `DEEPGRAM_API_KEY` | Only in the process performing transcription, if enabled |
| Participant/hub/operator credentials | Generated per-role secrets or server-side token records; never committed |
| `SERVER_URL` | Each local hub; deployed public HTTPS origin |

The Render management API key belongs only in the deployer's secret environment. It must not appear in `render.yaml`, source, `.env.example`, application environment, logs, phone pages, or this document. A management key is not an application login token. Do not reuse the key pasted in conversation; rotate it first.

## Deployment steps

1. Finish and review the deployment patch locally; verify server import, tests, migrations, and Blueprint structure.
2. Make the intended revision available in the connected GitHub repository. Deploy the agreed branch/revision, not another agent's incomplete work.
3. In Render, choose New Blueprint and connect the repository containing `render.yaml`, or create equivalent free services via the API. Ensure GitHub repository access is authorized; an API key alone may not provide private-repository access.
4. Review that exactly the intended free web service and free database are selected, add runtime secrets through Render, and create the resources.
5. Wait for readiness and record the real public service URL and resource IDs without dumping configuration or secrets.
6. Seed demo users through the authenticated operator path and configure each laptop's hub URL and separate credentials.
7. Verify health, readiness, phone UI, and authenticated polling from both laptops on the actual event Wi-Fi. Also test a browser over cellular. Outbound HTTPS avoids LAN isolation but is still subject to the event network's internet restrictions.
8. Exercise two-user matching with simulated observations first; then integrate real authorized bands. Confirm pause/decline, partial device failure, and stale hub cleanup.
9. Restart or redeploy once and verify data remains in Postgres and expired lighting does not resume. Rehearse opening the service before the demo to allow for cold startup.

## Free tier limits and evidence

Render free web services sleep after 15 minutes without inbound traffic and may take about a minute to wake. Local filesystem changes, including SQLite files, are lost on restart, redeploy, or spin-down. Free Postgres expires after 30 days and has no backups; export useful data before expiry. Free web services cannot use persistent disks or paid pre-deploy commands. Usage limits still apply, and Claude/transcription API costs are separate from hosting.

Sources: [Render free resources](https://render.com/docs/free), [FastAPI deployment](https://render.com/docs/deploy-fastapi), and [Blueprint reference](https://render.com/docs/blueprint-spec).

## Completion report

Return the deployed HTTPS URL, exact deployed revision, selected plans, database migration status, files changed, checks passed, and remaining hardware blockers. Clearly distinguish prepared configuration from resources actually created and a service actually verified live.
