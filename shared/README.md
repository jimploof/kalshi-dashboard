# Shared Contracts

This directory is reserved for generated and shared artifacts between the frontend and backend.

## Intended Contents

- OpenAPI schema exported from the FastAPI backend (`/openapi.json`)
- TypeScript types generated from the OpenAPI schema
- Other cross-layer contracts as needed

## Type-sharing Strategy

Backend response types are **never** manually duplicated in the frontend.
All frontend API types are **generated** from the backend's OpenAPI schema.

Generation tooling will be added once the first real API routes are implemented.
Candidates: [`@hey-api/openapi-ts`](https://heyapi.dev), [`openapi-generator-cli`](https://openapi-generator.tech).

## Generation Workflow (planned)

1. Start the backend: `docker compose up backend`
2. Fetch the schema: `curl http://localhost:8000/openapi.json > shared/openapi.json`
3. Generate TS types: `<tool> --input shared/openapi.json --output shared/generated/`
4. Import types in Angular services from `shared/generated/`
