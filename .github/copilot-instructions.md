# Copilot Instructions

## Project Overview
This is a full-stack monorepo for a **local, internal-only trading workstation** built on top of the **public Kalshi APIs**.

The platform is intended to run on **Windows with WSL2 Ubuntu**, primarily for **localhost** use, and is designed as a **single-user internal workstation**, not a public internet-facing SaaS product.

The primary product goals are:

- monitor Kalshi markets in real time
- display richer charting and market structure than the native UI
- provide a dense single-screen trading workstation layout
- support working orders, fills, positions, and queue position visibility
- support client-side parent/child contingent order workflows
- persist raw market data for replay and historical analysis
- remain generalized enough to support sports, crypto, and other Kalshi market categories

All code suggestions must align with this architecture and the conventions below.

---

## Current Phase Rule
The project is currently in the **initial scaffold phase**.

At this phase, Copilot should focus on:
- repository structure
- Angular foundation
- FastAPI foundation
- Docker Compose wiring
- PostgreSQL and Redis container wiring
- Angular dev proxy setup
- backend configuration and CORS foundation
- OpenAPI/type-generation foundation
- documentation scaffolding
- minimal health/test endpoints only

At this phase, Copilot must **not**:
- implement Kalshi trading logic
- implement order orchestration
- implement contingent order workflows
- implement charting features in detail
- implement queue position workflows
- invent speculative product features
- invent speculative domain models beyond basic skeletons
- introduce extra infrastructure beyond the approved stack

Prefer the smallest correct scaffold that matches the approved architecture.

---

## Repository Structure
- `frontend/` — Angular 21 application
- `backend/` — FastAPI Python application
- `shared/` — shared contracts, schemas, generated types, and cross-layer artifacts when needed
- `docs/` — architecture, planning, setup, and design documentation
- `.github/copilot-instructions.md` — these instructions

Never mix frontend and backend code.
Never suggest imports that cross the frontend/backend boundary directly.
Never suggest frontend code that calls Kalshi directly.

---

## Core Architecture Rules

### 1. Backend owns all Kalshi access
The backend is the only layer allowed to communicate with Kalshi.

The backend must own:
- authentication and signing
- WebSocket session management
- REST scheduling and rate limiting
- retries and reconnect logic
- normalization of exchange data
- persistence of raw events
- contingent order orchestration
- queue position lookup
- replay and recovery logic

The frontend must never call Kalshi directly under any circumstances.

---

### 2. WebSockets are the primary live transport
The system is **WebSocket-first** for live market state.

Use WebSockets whenever the public Kalshi API supports them for:
- market ticker updates
- public trades
- order book updates
- user order updates
- fills
- positions
- other documented private or lifecycle streams

Do not replace live WebSocket flows with REST polling shortcuts.

---

### 3. REST is reserved and must be minimized
REST must only be used when necessary, such as:
- event and market discovery
- bootstrap hydration
- reconnect recovery
- queue position lookup
- account limits lookup
- market metadata lookup
- order placement
- order amendment
- order decrease
- order cancellation
- other actions only available via REST

Do not use REST as the primary live transport for market data.

---

### 4. Protect write capacity
Kalshi REST usage must be treated as a constrained resource.

The system must preserve write capacity for execution-critical actions:
- create order
- batch create child orders
- cancel order
- batch cancel orders
- amend order
- decrease order

Optional reads must never starve trading writes.

---

### 5. Separate read and write scheduling
The backend must maintain separate REST scheduling and rate-limit protection for:
- read requests
- write requests

The scheduler must support:
- priorities
- deduplication
- coalescing duplicate reads
- protected write reserve
- deferred or dropped low-priority reads
- structured logging of scheduler decisions

No Kalshi request may bypass the scheduler.

---

### 6. Queue position is pull-based
Queue position must be treated as REST-only unless public Kalshi documentation explicitly changes.

Do not design queue position as a pushed live WebSocket field.

Queue position should only be fetched when useful, such as:
- when an order first becomes resting
- after amend or decrease
- for selected orders
- for visible resting orders
- during reconnect recovery if needed

Do not aggressively poll queue position for every order.

---

### 7. Persist raw events before deep derivation
Raw inbound exchange events must be preserved.

Persist raw WebSocket events before or alongside deeper derived processing.

Raw events are the authoritative historical source.
Derived views may include:
- 1-second bars
- bid/ask overlays
- volume panels
- spread panels
- imbalance metrics
- ladder checkpoints
- working order views
- fills views
- positions views

Derived state must be rebuildable from raw event history plus documented recovery flows.

---

### 8. Domain-agnostic core
The platform must be generalized enough to support:
- basketball
- football
- golf
- UFC
- bitcoin
- other Kalshi market categories

Do not hardcode sports-specific assumptions into the shared core architecture.

The core platform must be built around:
- event
- market
- market group / related markets
- order book
- trade tape
- positions
- orders
- derived analytics
- optional domain metadata

Sports-specific or asset-specific context may exist as optional display modules, but not as core architectural assumptions.

---

### 9. Supported public-API build only
Do not depend on undocumented or reverse-engineered Kalshi APIs.
Do not build required features around private consumer-app endpoints.
Do not assume public developer API support for sports play-by-play or live sports telemetry unless explicitly documented.

The supported build must rely only on documented public Kalshi APIs and WebSockets.

---

## Approved Core Stack

### Frontend
- Angular 21
- TypeScript (strict mode)
- SCSS

### Backend
- Python 3.12
- FastAPI
- Pydantic v2
- `uv` for package management

### Data / Infra
- PostgreSQL for durable persistence
- Redis for cache / ephemeral coordination
- Docker Compose for local development
- local/internal deployment assumptions only
- prefer minimal infrastructure
- do not introduce extra moving parts unless justified

### Current architecture posture
- local internal workstation
- localhost-first
- single-user oriented
- modular monolith preferred over microservices
- backend-owned realtime state
- replay-ready from day one

Do not introduce alternate frameworks, runtimes, or infrastructure without explicit approval.

---

## Local Docker and Networking Rules

The application is designed for local internal use on **Windows with WSL2 Ubuntu** using **Docker Compose**.

### Locked Docker service layout
Use exactly these initial services:
- `frontend` — Angular container
- `backend` — FastAPI application container
- `postgres` — PostgreSQL container
- `redis` — Redis container

Do not assume a single-container architecture unless explicitly requested.
Do not introduce nginx initially.
Do not introduce a separate worker service initially.
Do not introduce extra infrastructure unless explicitly approved.

### Browser Access
The frontend is typically accessed from the browser using:
- `http://localhost:4200`
- `http://127.0.0.1:4200`

Treat `localhost` and `127.0.0.1` as different origins for CORS purposes.

### Container Networking
Containers must communicate with each other using **Docker service names**, never `localhost`.

Examples:
- frontend dev proxy -> backend service
- backend -> postgres service
- backend -> redis service

Do not hardcode container hostnames into frontend browser code.

### Frontend API Access
During local development, frontend code should prefer **proxy-relative paths** such as:
- `/api/...`
- `/ws/...`

Do not hardcode backend URLs into Angular components or services.
All frontend base URLs must come from environment or configuration.

### Proxy and CORS
Prefer Angular dev proxying during local development to reduce browser CORS issues.

Backend code must still support explicit CORS configuration for approved local development origins.

CORS allowed origins must come from configuration and should explicitly support local development origins when needed, including:
- `http://localhost:4200`
- `http://127.0.0.1:4200`

Do not use broad wildcard CORS configuration unless explicitly approved.

### Backend Design Implications
Backend API and WebSocket routes should be designed to work cleanly behind a frontend dev proxy.

Do not assume the browser will call the backend using Docker service names.
Do not assume frontend and backend share the same origin unless proxying is configured.

---

## Environment and Configuration Rules

### Config ownership
Use committed example templates and local real env files.

Expected structure:
- `.env.example` — root/shared Docker Compose and cross-service defaults
- `backend/.env.example` — backend application configuration
- `frontend/.env.example` — frontend non-secret configuration only

Real local files such as:
- `.env`
- `backend/.env`
- `frontend/.env`

must not be committed.

### Secrets
Never hardcode secrets, tokens, or credentials.
Never place backend secrets into frontend-exposed configuration.
Frontend config must contain only non-secret, browser-safe values.

### Compose vs app config
Use root-level env for Compose/shared wiring.
Use backend env for backend runtime/configuration.
Use frontend env only where frontend configuration is genuinely needed.

Do not invent scattered ad hoc environment variable patterns.

---

## Angular 21 — Core Conventions

### Components
- ALL components must be standalone. Never use or suggest NgModules.
- Always use `ChangeDetectionStrategy.OnPush` on every component.
- Prefer zoneless-compatible patterns and do not rely on Zone.js-driven implicit change detection.
- Use the `inject()` function for dependency injection, never constructor injection.

### State Management
- Use Angular Signals exclusively for UI state management.
- Never suggest RxJS `Subject`, `BehaviorSubject`, or `EventEmitter` for UI state.
- RxJS is acceptable only for:
  - HTTP calls via `HttpClient`
  - explicit stream interop where unavoidable
- Prefer signals and computed/effect patterns for component state.

### Templates
- Always use the new control flow syntax: `@if`, `@for`, `@switch`.
- Never suggest `*ngIf`, `*ngFor`, or `*ngSwitch`.
- Always include a `track` expression in `@for` loops.

### Styling
- Use SCSS for all component styles.
- Use `ViewEncapsulation.Emulated` unless there is a clear reason otherwise.
- Do not use inline styles for production UI structure.

### Frontend Architecture Rules
- The UI must be a dense workstation-style application, not a marketing-style layout.
- The frontend must consume normalized backend state.
- All exchange-originating live state must come from the backend.
- Components must be designed for:
  - main chart stack
  - ladder
  - tape
  - order entry
  - working orders
  - fills
  - positions
  - related markets
  - contingent order controls
- Never place exchange or business orchestration logic directly in presentation components.

---

## TypeScript Conventions
- Always use strict TypeScript. No `any` under any circumstance.
- Prefer `type` over `interface` unless declaration merging is needed.
- Always define return types on public methods and functions.
- Use `readonly` for properties that should not be mutated.
- Always use optional chaining `?.` and nullish coalescing `??` over manual null checks.
- Prefer small, explicit DTOs and view models.
- Do not manually type API responses independently from backend contracts.

---

## Python & FastAPI Conventions

### Environment & Packaging
- Use `uv` for all package management. Never suggest `pip install` directly.
- All dependencies are defined in `pyproject.toml`.
- Python version is 3.12.

### FastAPI Patterns
- Always use Pydantic v2 models for all request and response schemas.
- Always define explicit response models on every route using `response_model=`.
- Use dependency injection via `Depends()` for shared logic such as auth, DB access, settings, and service resolution.
- Organize routes using `APIRouter`; never define routes directly on the `app` instance.
- Always use `async def` for route handlers unless there is a very strong reason not to.
- Prefer a modular monolith structure with clear backend module boundaries.

### Backend Architecture Rules
- The backend must separate concerns for:
  - Kalshi connectivity
  - stream ingestion
  - order orchestration
  - REST scheduling
  - persistence
  - replay
  - frontend-facing APIs
- In-memory live state is acceptable for current state, but durable history belongs in PostgreSQL.
- Do not design the backend as microservices unless explicitly approved.
- Do not introduce unnecessary infrastructure for a localhost-only internal system.

### Code Style
- Ruff is the linter and formatter. Follow Ruff defaults.
- Never suggest `print()` for debugging — use Python `logging`.
- Always use type hints on every function parameter and return value.
- Use structured, explicit service boundaries rather than giant utility files.

---

## Product Scope — Version 1

Version 1 must provide a usable live trading workstation with:
- primary YES 1-second bars
- bid/ask overlay
- volume bars
- spread panel
- order-book imbalance panel
- live ladder
- replayable ladder tied to chart cursor timestamp
- trade tape
- related markets panel
- working orders panel
- fills panel
- positions panel
- queue position display
- parent/child contingent order workflow
- real-time amend / decrease / cancel controls
- recent replay from stored raw data

Do not treat the visual trading surface as optional.
The chart stack and order-management surface are core Version 1 deliverables.

---

## Deferred / Later Scope
The following may be considered later, but are not assumed to be core V1 requirements:
- AI-assisted recommendations
- external sports telemetry integration
- advanced backtesting engine
- multi-user support
- internet-facing deployment
- extra infrastructure beyond PostgreSQL and Redis unless justified by a concrete need

---

## Testing

### Frontend (Angular)
- Use Vitest for all unit tests. Never suggest Karma or Jasmine.
- Use Angular Testing Library for component tests.
- Test files live alongside source files: `component.spec.ts`.

### Backend (Python)
- Use pytest for all tests.
- Use `httpx` and FastAPI testing patterns for API endpoint tests.
- Test files live in `backend/tests/`.
- Always mock external dependencies in unit tests.
- Prefer deterministic tests for:
  - scheduler behavior
  - contingent order orchestration
  - replay derivation
  - recovery flows

---

## API Contract & Type Sharing
- FastAPI must expose an OpenAPI schema at `/openapi.json`.
- Angular services must never manually type API responses — types must be generated from the OpenAPI schema.
- All API base URLs must come from environment variables or configuration, never hardcoded.
- All HTTP calls in Angular go through a dedicated service class, never directly in components.
- Shared contracts belong in `shared/` or are generated into that area.

---

## Explicitly Forbidden Patterns

### Angular
- NgModule declarations
- constructor-based dependency injection
- `*ngIf`, `*ngFor`, `*ngSwitch`
- `BehaviorSubject` or `Subject` for UI state
- `ngOnChanges` for patterns that should be handled by signals/effects
- direct Kalshi HTTP/WebSocket calls from frontend
- business orchestration logic inside visual components
- hardcoded backend origins in components or feature code

### Python
- `pip install` commands
- `print()` statements
- untyped function signatures
- direct route definitions on `app`
- Pydantic v1 syntax such as `.dict()` or `.parse_obj()`
- backend logic that bypasses the REST scheduler for Kalshi calls
- undocumented assumptions about Kalshi exchange behavior
- permissive CORS defaults without explicit configuration

### General
- `any` TypeScript type
- inline styles for core layout structure
- hardcoded secrets, API keys, or URLs
- `console.log` in production code
- REST polling for live market data when a documented WebSocket feed exists
- aggressive queue-position polling
- frontend/backend boundary violations
- hardcoded sports-only architecture assumptions
- private or reverse-engineered API dependencies
- using `localhost` for container-to-container communication
- inventing extra infrastructure or product scope during the scaffold phase

---

## Recovery and Reliability Rules
- Design for reconnect and recovery from the start.
- Store raw events so recent replay is always possible.
- Preserve both exchange timestamps and local ingest timestamps.
- Normalize times to UTC for querying and replay.
- Use deterministic recovery flows rather than ad hoc refresh logic.
- Optional reads may be dropped or deferred under pressure.
- Execution-critical writes must be protected.

---

## Copilot Working Rules
When generating code for this repo:

1. prefer the smallest correct slice
2. follow the approved stack and patterns above
3. keep frontend, backend, and shared contracts cleanly separated
4. preserve architectural guardrails
5. explain assumptions when documentation is not explicit
6. prefer WebSocket-driven live state over REST polling
7. prefer backend ownership over frontend shortcuts
8. prefer raw event preservation over derived-only state
9. prefer modular monolith patterns over premature service splitting
10. do not introduce new frameworks, infra, or patterns without clear justification
11. keep local Docker, proxy, and CORS behavior compatible with localhost-based browser testing
12. respect the current scaffold phase and do not jump ahead into business logic or speculative features