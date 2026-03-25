# Technical Architecture

## Overview

<!-- TODO: Describe the overall system architecture and guiding principles. -->

## Components

### Frontend (Angular 21)

<!-- TODO: Describe the Angular application architecture — standalone components, signals, OnPush, proxy setup. -->

### Backend (FastAPI)

<!-- TODO: Describe the FastAPI modular monolith — router structure, config, CORS, WebSocket handling. -->

### Data Layer

<!-- TODO: Describe PostgreSQL schema strategy and Redis usage for ephemeral state. -->

## Data Flow

### Live Market Data (WebSocket-first)

<!-- TODO: Document how live market state flows from Kalshi → backend WebSocket sessions → frontend. -->

### REST Endpoints

<!-- TODO: Document REST API surface — markets discovery, order management, replay. -->

## Kalshi Integration

<!-- TODO: Document Kalshi API integration approach — auth/signing, REST scheduler, WebSocket session manager. -->

## Networking

### Docker Compose Topology

<!-- TODO: Describe internal service-name networking vs browser-facing localhost access. -->

### Angular Dev Proxy

<!-- TODO: Describe /api and /ws proxy configuration and why containers use service names. -->

## Deployment

<!-- TODO: Document Docker Compose local deployment steps and environment configuration. -->
