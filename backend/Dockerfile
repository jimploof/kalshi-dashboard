FROM python:3.12-slim

# Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only what hatchling needs to resolve + install deps first.
# This layer is cached until pyproject.toml or app/ source changes.
COPY pyproject.toml ./
COPY app/ ./app/

# Install runtime + dev dependencies into the system Python.
# '[dev]' makes pytest, ruff, etc. available for `docker compose exec backend pytest`.
RUN uv pip install --system --no-cache ".[dev]"

# Copy the rest (tests/, .env.example, etc.) after the install layer.
COPY . .

EXPOSE 8000

# --reload watches for source changes; safe for dev because of volume mount
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
