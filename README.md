# Reseno

Reseno is a resume workspace with a React frontend and a FastAPI backend. It
supports structured resume editing, workspace persistence, imports, AI agent assisting.

## Stack

- Frontend: React, TypeScript, Vite, Tailwind CSS
- Backend: FastAPI, SQLite
- Package management: pnpm, uv

## Requirements

- Python 3.12 or newer
- uv
- Node.js and pnpm

## Configuration

Backend defaults are documented in `backend/.env.example`. To customize them,
copy it to `backend/.env`, which Git ignores. `APP_ENV_FILE` selects another
configuration file. Process environment variables take precedence; blank key
variables use the values from the file. Unspecified settings use code defaults.

Runtime data lives under `APP_DATA_DIR` (default `~/.reseno`). Unless explicitly
set, `APP_DB_PATH`, `APP_STORAGE_DIR`, and `APP_USER_SETTINGS_PATH` resolve to
`app.db`, `storage`, and `user_settings.json` within that directory.

The encryption and JWT keys, `RESENO_MASTER_KEY` and `RESENO_JWT_SECRET`, are
stored in `.env`. On first startup, missing or blank keys are generated and
saved together, creating the file if needed with owner-only permissions.
Existing keys and other settings are preserved. A complete key pair supplied
through the environment or configuration file requires no configuration writes.
Back up `.env` (or externally managed keys) together with the databases and
storage. Missing keys for existing databases must be restored; they are never
silently replaced. Container deployments that generate keys must mount a writable
configuration directory so the backend can atomically replace `.env`; an empty
single-file bind mount is insufficient. Alternatively, supply both stable keys
through the environment or a prefilled configuration file. Persist the keys
alongside the data directory.

There are no default credentials. On first opening Reseno locally, create the
single owner username and password on the setup page. Authentication is stored
separately in `~/.reseno/auth.db`; the resume database remains unchanged.

Owner sessions use JWTs valid for 36 hours after issuance or refresh. Browser
sessions are kept in local storage and shared by tabs on the same origin.
Signing in or out synchronizes open tabs. Valid sessions survive browser restarts.

### GitHub login

Create the owner with a username and password, then choose **Set up and connect
GitHub** in account settings. Confirm the app creation and authorization on GitHub
to bind your account. Reseno fills in the instance address and callback URLs and
saves the configuration automatically; no OAuth credentials need to be copied or
added to `.env`.

Each instance uses a private GitHub App owned by its deployment owner, created
through the [GitHub App Manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest).
There is no shared authentication service. The app requests no access to repository
contents or email. Its client secret is encrypted in `auth.db` with
`RESENO_MASTER_KEY`; back up the key together with that database.
GitHub access and refresh tokens are used only during authentication and are not
stored. Local JWTs are never included in callback URLs.

Use the instance's normal browser address when configuring GitHub. Serve the
frontend and proxy `/api` to the backend on that same origin; Vite already provides
this proxy locally. Remote deployments require HTTPS. Local HTTP is supported on
`localhost` and loopback IP addresses. Keep the configured hostname and port stable
so the browser returns to the same instance after authorization.

The GitHub sign-in button is always visible. If GitHub is not configured or bound,
clicking it shows a notice to sign in with a password and connect GitHub in settings.
Only the bound GitHub identity can sign in as the owner. Password login remains
available, and the binding can be removed in account settings. If you cancel
authorization after creating the app, return to settings and choose **Connect
GitHub** to finish.

## Start The Backend

```bash
cd backend
uv sync --locked
uv run --locked playwright install --only-shell chromium
uv run --locked uvicorn app.main:create_app --factory --reload
```

The backend listens on `http://127.0.0.1:8000`.

Run one worker and one replica per workspace. Agent execution and SSE replay
belong to the running process; multiple workers cannot share them. The backend
holds file locks on its business database, authentication directory and storage
for its entire lifetime, and refuses a second instance that shares any of them.
Keep these locations on persistent storage with working file-lock support.
Do not load-balance one workspace across independent backend replicas.

The application factory initializes configuration explicitly. Importing Python
modules and reading settings do not create files or modify process environment
variables. Public Swagger, ReDoc and OpenAPI endpoints are disabled; the Python
application exposes `app.openapi()` for contract tooling.

Database startup checks preserve existing data and reject incompatible schemas.
Back up the keys, databases and storage together and use a release that supports
the existing schema. Configure separate unused data, database and storage paths
when creating a new workspace.

Playwright's Chromium renders dynamic job pages and resume exports. It does not
require Google Chrome to be installed. Exports reuse one browser with a separate
context per request; up to four requests can wait or render at once. Set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` only when using an external Chromium explicitly.
On a Linux server, install Chromium and its system dependencies during the build
instead:

```bash
uv run --locked playwright install --with-deps --only-shell chromium
```

## Start The Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

The frontend listens on `http://127.0.0.1:5173`.

## Docker

Build from the repository root, then start one container:

```bash
DOCKER_BUILDKIT=1 docker build --pull -t reseno:local .
docker run -d --name reseno --init --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --mount type=volume,source=reseno-data,target=/data \
  --shm-size=256m \
  reseno:local
```

The image serves the production frontend and API together on port 8000 and
includes Chromium headless shell for exports and dynamic web pages. Build tools,
development dependencies, local configuration and runtime data are excluded.
The container runs as UID/GID 10001; existing bind-mounted directories must be
writable by that user.

Create the owner once from inside the running container:

```bash
docker exec -it reseno python -m app.setup_owner
```

The command prompts for credentials with hidden password input. Open
`http://localhost:8000` and sign in. Browser requests forwarded through Docker's
network do not qualify as loopback requests for first-owner setup.

The `/data` volume contains the databases, files, settings and generated `.env`
keys. Keep this volume when replacing the container and back up its complete
contents with the container stopped. Use a separate volume for each workspace.

Change the host-side port in `-p` to use another local port. For remote access,
put the container behind an HTTPS reverse proxy that forwards the entire site,
including `/api`, and supports unbuffered SSE responses. Serve Reseno at the
domain root. The internal port remains 8000; changing the public hostname or
port does not require changing the render URL or CORS configuration.

Docker sets `FRONTEND_RENDER_BASE_URL=http://127.0.0.1:8000` so exports render
through the same container, and leaves `BACKEND_CORS_ORIGINS` empty because the
frontend and API share an origin. `PDF_RENDER_TIMEOUT_MS` defaults to 30000;
override it with `-e PDF_RENDER_TIMEOUT_MS=60000` if exports need more time.

## License

MIT License. See `LICENSE`.
