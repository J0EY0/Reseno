# ResuMate

ResuMate is a resume workspace with a React frontend and a FastAPI backend. It
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

Backend defaults are documented in `backend/.env.example`. The backend stores
runtime data outside the Git working tree under `~/.resumate` by default.

There are no default credentials. On first opening ResuMate locally, create the
single owner username and password on the setup page. Authentication is stored
separately in `~/.resumate/auth.db`; the resume database remains unchanged.

## Start The Backend

```bash
cd backend
uv sync
uv run playwright install --only-shell chromium
uv run uvicorn app.main:app --reload
```

The backend listens on `http://127.0.0.1:8000`.

Playwright's Chromium renders dynamic job pages and resume exports. It does not
require Google Chrome to be installed. On a Linux server, install Chromium and
its system dependencies during the build instead:

```bash
uv run playwright install --with-deps --only-shell chromium
```

## Start The Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

The frontend listens on `http://127.0.0.1:5173`.

## License

MIT License. See `LICENSE`.
