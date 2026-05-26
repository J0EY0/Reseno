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

The default local login is:

- Username: `admin`
- Password: `ResuMate@2026`

## Start The Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

The backend listens on `http://127.0.0.1:8000`.

## Start The Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

The frontend listens on `http://127.0.0.1:5173`.

## License

MIT License. See `LICENSE`.
