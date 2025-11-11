# dt-relay

dt-relay is a lightweight relay that ingests metrics into Dynatrace from curated tools. The first tool, `/dt-relay/datadomain`, turns Data Domain capacity values into Dynatrace metrics using the Metrics v2 API. The project is structured so additional tools can be added under `apps/` without touching the core server code.

## Features

- HTTPS front-end terminated by Nginx on port 443
- Server-rendered UI for entering Data Domain metrics
- Multi-tenant Dynatrace support with shared or per-tenant tokens
- Extensible architecture: add new apps under `apps/` and register automatically
- Secure-by-default headers, no token echoing or logging

## Repository Layout

```
dt-relay/
├── apps/
│   ├── core/                # shared templates (landing page)
│   └── datadomain/          # Data Domain app implementation
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

1. Generate a self-signed certificate (valid for `localhost`):

   ```bash
   mkdir -p reverse-proxy/certs
   openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
     -keyout reverse-proxy/certs/privkey.pem \
     -out reverse-proxy/certs/fullchain.pem \
     -subj "/CN=localhost"
   ```

2. Ensure your user can communicate with the Docker daemon. If you see
   `permission denied while trying to connect to the Docker daemon socket`,
   add yourself to the `docker` group and log back in:

   ```bash
   sudo groupadd docker 2>/dev/null || true
   sudo usermod -aG docker "$USER"
   newgrp docker
   ```

3. Start the stack:

   ```bash
   AUTH_PASSWORD=changeme docker compose up -d --build
   ```

4. Navigate to <https://localhost/>. Accept the browser warning for the self-signed cert.

5. Visit <https://localhost/dt-relay/datadomain> to use the Data Domain form.

## Production Deployment (corporate certs)

1. Place the provided TLS certificate and key in `reverse-proxy/certs/fullchain.pem` and `reverse-proxy/certs/privkey.pem` respectively (do not commit real certs).
2. Set secure environment variables for production (never use `config/defaults.env` directly for secrets). Example:

   ```bash
   export AUTH_PASSWORD="super-secret"
   export DEFAULT_DIM_SYSTEM="dd-prod"
   export DEFAULT_DIM_SITE="primary"
   export METRIC_PREFIX="custom.ddfs"
   docker compose up -d --build
   ```

3. Update DNS to point to the host running dt-relay. No code changes are required when swapping certificates or hostnames.

## Configuration

### Environment Variables

| Variable             | Description                                                    | Default         |
|----------------------|----------------------------------------------------------------|-----------------|
| `AUTH_PASSWORD`      | Required password to submit the form.                          | (none / must set) |
| `DEFAULT_DIM_SYSTEM` | Default `system` dimension when the form is empty.             | `dd-system-01`  |
| `DEFAULT_DIM_SITE`   | Default `site` dimension when the form is empty.               | `primary-dc`    |
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
https://<your-host>/dt-relay/datadomain?system=dd-system-01&site=primary-dc&totalSpace=543.5&usedSpace=443.43&availableSpace=100.07&preComp=632023121083777&postComp=75624078408985&totalCompFactor=8.3531
```

## Synthetic Validation Tip

Synthetic monitors can confirm a successful ingest by verifying that the page contains:

```html
<div id="ingest-result">SUCCESS</div>
```

## Adding a New Subpage

1. Create a directory under `apps/<slug>/` with `routes.py`, `metrics.py` (or other helpers), templates, and optional utilities.
2. Implement a `register(app)` function inside `routes.py` that returns `(blueprint, metadata)` where `metadata` includes `slug` and `description`.
3. Use the shared utilities from `server/util.py` for Dynatrace interactions.
4. The server automatically detects new sub-apps on startup—no additional wiring is necessary.

Keep HTML simple and rely on server-side rendering. Avoid logging sensitive fields.

## Example Workflow

1. Launch the stack.
2. Browse to `/dt-relay/datadomain` with prefilled query parameters.
3. Choose one or more tenants, provide the site password and tokens.
4. Submit the form. The results page reports per-tenant status with payload previews. All successes display `<div id="ingest-result">SUCCESS</div>`.
