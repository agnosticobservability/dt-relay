# dt-relay

dt-relay is a lightweight relay that ingests metrics into Dynatrace from curated tools. It ships with two built-in experiences:

- `/dt-relay/datadomain` turns Data Domain capacity values into Dynatrace metrics using the Metrics v2 API.
- `/dt-relay/metrics` lets you submit arbitrary metrics with custom dimensions.

The project is structured so additional tools can be added under `apps/` without touching the core server code.

## Features

- HTTPS front-end terminated by Nginx on port 443
- Server-rendered UI for entering Data Domain metrics
- Generic metrics builder for arbitrary key/value pairs and dimensions
- Multi-tenant Dynatrace support with shared or per-tenant tokens
- Extensible architecture: add new apps under `apps/` and register automatically
- Secure-by-default headers, no token echoing or logging

## Repository Layout

```
dt-relay/
├── apps/
│   ├── core/                # shared templates (landing page)
│   ├── datadomain/          # Data Domain app implementation
│   └── metrics/             # Generic metrics builder app
│       ├── metrics.py       # builds Dynatrace lines protocol payloads
│       ├── routes.py        # form, ingest handler, health endpoint
│       ├── templates/       # HTML templates for form and results
│       └── views.py         # template name constants
├── config/
│   ├── defaults.env         # example/default environment configuration
│   └── tenants.json         # tenant definitions (authoritative)
├── reverse-proxy/
│   ├── certs/               # mount self-signed or real TLS certificates here
│   └── nginx.conf           # TLS termination + proxy config
├── server/
│   ├── app.py               # Flask application factory and sub-app loader
│   └── util.py              # shared helpers (tenants, metrics, HTTP ingest)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Prerequisites

- Docker and Docker Compose (v2) installed
- Dynatrace API ingest tokens for the tenants you want to target

## Quick Start (self-signed development certs)

> **Note**
> A self-signed certificate for `localhost` is bundled in `reverse-proxy/certs` so
> you can get started immediately. Replace it with trusted certificates for any
> non-development use.

1. Ensure your user can communicate with the Docker daemon. If you see
   `permission denied while trying to connect to the Docker daemon socket`,
   add yourself to the `docker` group and log back in:

   ```bash
   sudo groupadd docker 2>/dev/null || true
   sudo usermod -aG docker "$USER"
   newgrp docker
   ```

2. Start the stack:

   ```bash
   AUTH_PASSWORD=changeme docker compose up -d --build
   ```

   You can also use the helper script described below to manage the stack.

3. Navigate to <https://localhost/>. Accept the browser warning for the bundled
   self-signed development certificate.

4. Visit <https://localhost/dt-relay/datadomain> to use the Data Domain form.

5. Visit <https://localhost/dt-relay/metrics> to submit generic metrics with
   custom dimensions and values.

### Helper script

Use `scripts/dt-relay.sh` to start, stop, or restart the Docker stack with a single
command. The script automatically prefers a local `.env` file and falls back to
`config/defaults.env` if one exists.

To stop the stack, update the repository, and start everything back up again in a
single command, use `scripts/update.sh`. Any arguments you provide are forwarded to
`git pull`, allowing you to specify a remote or refspec as needed. Submodules are
also updated automatically.

```bash
# Start (builds images if needed)
./scripts/dt-relay.sh start

# Stop the stack
./scripts/dt-relay.sh stop

# Restart the stack
./scripts/dt-relay.sh restart

# Stop the stack, pull the latest code, and restart
./scripts/update.sh
```

## Logs

- Application logs are written to `logs/dt-relay.log`. The directory ships with the
  repository and is mounted read/write into the container by `docker compose`.
- The container entrypoint adjusts permissions on the mounted directory when the
  stack starts so that logs are still captured when the host path is owned by root.
- Review the file with `tail -f logs/dt-relay.log` while testing ingest flows.
- Logs intentionally omit sensitive values like Dynatrace tokens and form payloads.

## Production Deployment (corporate certs)

1. Place the provided TLS certificate and key in `reverse-proxy/certs/fullchain.pem` and `reverse-proxy/certs/privkey.pem` respectively (do not commit real certs).
2. Set secure environment variables for production (never use `config/defaults.env` directly for secrets). Example:

   ```bash
   export AUTH_PASSWORD="super-secret"
   export DEFAULT_DIM_HOST="dd-prod"
   export DEFAULT_DIM_ENVIRONMENT="primary"
   export METRIC_PREFIX="custom.ddfs"
   docker compose up -d --build
   ```

3. Update DNS to point to the host running dt-relay. No code changes are required when swapping certificates or hostnames.

## Configuration

### Environment Variables

| Variable             | Description                                                    | Default         |
|----------------------|----------------------------------------------------------------|-----------------|
| `AUTH_PASSWORD`      | Required password to submit the form.                          | `(blank)` (set explicitly) |
| `DEFAULT_DIM_HOST`   | Default `host` dimension when the form is empty.               | `dd-system-01`  |
| `DEFAULT_DIM_ENVIRONMENT` | Default `environment` dimension when the form is empty.         | `primary-dc`    |
| `METRIC_PREFIX`      | Metric prefix when tenants do not specify their own.           | `custom.ddfs`   |
### Tenants

Tenants are defined in `config/tenants.json`. Each entry contains:

- `id` – unique slug used in the UI and configuration
- `label` – friendly display name
- `baseUrl` – Dynatrace tenant base URL (e.g., `https://abc123.live.dynatrace.com`)
- `metricPrefix` (optional) – override the metric prefix for this tenant
- `staticDims` (optional) – dimensions automatically merged into every line

Example:

```json
[
  {
    "id": "prod",
    "label": "Prod Tenant",
    "baseUrl": "https://abc12345.live.dynatrace.com",
    "metricPrefix": "custom.ddfs",
    "staticDims": { "env": "prod" }
  },
  {
    "id": "qa",
    "label": "QA Tenant",
    "baseUrl": "https://abc12345.qa.live.dynatrace.com",
    "staticDims": { "env": "qa" }
  }
]
```

Restart the stack after editing this file.

## Health Check

Verify the application is healthy via HTTPS:

```bash
curl -k https://localhost/dt-relay/health
```

The response should be `ok` with status `200`.

## Prefill URL Example

You can pre-fill the Data Domain form using query parameters:

```
https://<your-host>/dt-relay/datadomain?host=dd-system-01&environment=primary-dc&totalBytes=597584569696256&usedBytes=493636740406313&availableBytes=103947829289943
```

## Synthetic Validation Tip

Synthetic monitors can confirm a successful ingest by verifying that the page contains:

```html
<div id="ingest-result">SUCCESS</div>
```

## Generic Metrics App

The generic metrics app at `/dt-relay/metrics` is ideal for one-off payloads or
testing new metric definitions without adding code. Provide:

- One or more Dynatrace tenants and either a shared token or per-tenant tokens.
- Optional metric prefix overrides (defaults to the global `METRIC_PREFIX`).
- Arbitrary dimension key/value pairs merged with tenant static dimensions.
- Any number of metric name/value pairs; only numeric values generate lines.

The form supports query-string prefill for keys, values, and timestamps using
`dim_key`, `dim_value`, `metric_key`, `metric_value`, and `ts` parameters. Leave
values blank to start from the configured defaults.

## Adding a New Subpage

1. Create a directory under `apps/<slug>/` with `routes.py`, `metrics.py` (or other helpers), templates, and optional utilities.
2. Implement a `register(app)` function inside `routes.py` that returns `(blueprint, metadata)` where `metadata` includes `slug` and `description`.
3. Use the shared utilities from `server/util.py` for Dynatrace interactions.
4. The server automatically detects new sub-apps on startup—no additional wiring is necessary.

Keep HTML simple and rely on server-side rendering. Avoid logging sensitive fields.

## Example Workflow

1. Launch the stack.
2. Browse to `/dt-relay/datadomain` with prefilled query parameters.
3. Choose one or more tenants, provide the site password and tokens. If the form displays a configuration warning, set `AUTH_PASSWORD` on the server first.
4. Submit the form. The results page reports per-tenant status with payload previews. All successes display `<div id="ingest-result">SUCCESS</div>`.
5. Optionally navigate to `/dt-relay/metrics` to experiment with custom metric names, values, and dimensions using the same tenants and tokens.
