# Local Development

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose plugin) on WSL2 Ubuntu
- VS Code with the [Remote - WSL](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-wsl) extension
- Repo cloned inside the **Linux filesystem** (not under `/mnt/c/...`)

## Initial Setup

### 1. Create environment files

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Edit `backend/.env` with real values before starting (at minimum change `POSTGRES_PASSWORD`).

### 2. Build and start all services

```bash
docker compose up --build
```

First build downloads base images and installs dependencies — expect a few minutes.

### 3. Verify the stack

| URL | Expected response |
|-----|------------------|
| `http://localhost:4200` | Angular workstation shell |
| `http://localhost:8000/api/health` | `{"status":"ok"}` |
| `http://localhost:4200/api/health` | Same — proxied through Angular dev proxy |
| `http://localhost:8000/docs` | FastAPI interactive docs (Swagger UI) |

## Service Ports

| Service  | Internal port | Host port            |
|----------|--------------|----------------------|
| frontend | 4200         | 4200                 |
| backend  | 8000         | 8000                 |
| postgres | 5432         | not exposed (default)|
| redis    | 6379         | not exposed (default)|

To expose postgres/redis for local GUI tools (TablePlus, RedisInsight, etc.):

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
# Uncomment the ports you need, then:
docker compose up
```

## Common Commands

```bash
# Start all services (foreground)
docker compose up

# Rebuild after dependency changes
docker compose up --build

# Run in background
docker compose up -d

# Tail logs for a specific service
docker compose logs -f backend
docker compose logs -f frontend

# Stop all services
docker compose down

# Stop and remove all volumes (wipes DB data)
docker compose down -v
```

## Development Notes

### Frontend

- Live reload is enabled via volume mount (`./frontend:/app`)
- Angular dev proxy handles `/api` and `/ws` — no backend URL in browser code
- `node_modules` are isolated in an anonymous Docker volume; they persist across restarts

### Backend

- Auto-reload is enabled via `--reload` flag and volume mount (`./backend:/app`)
- OpenAPI docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Running Backend Tests

```bash
docker compose exec backend pytest
```

### Generating a package lockfile (after first build)

To commit a reproducible `package-lock.json` for the frontend, run `npm install`
locally (not inside the container) so the lockfile is written to the host filesystem
with your user's ownership:

```bash
cd frontend && npm install
git add package-lock.json && git commit -m 'chore: add frontend package-lock.json'
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `backend/.env: no such file` | Env file not created | `cp backend/.env.example backend/.env` |
| Port 4200 already in use | Another process on port 4200 | Stop the conflicting process |
| `Cannot connect to backend` in browser | Backend not ready yet | Wait for backend logs to show `Uvicorn running` |
| Angular proxy errors | `proxy.conf.json` target unreachable inside container | Confirm backend container is healthy: `docker compose ps` |
