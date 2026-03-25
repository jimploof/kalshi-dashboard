FROM python:3.12-slim

# Install uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy all source so hatchling can build the package
COPY . .

# Install the project and all its dependencies into the system Python
RUN uv pip install --system --no-cache .

EXPOSE 8000

# --reload watches for source changes; safe for dev because of volume mount
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
