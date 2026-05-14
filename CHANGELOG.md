# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.1.0] — 2026-05-13

### Added

- Hybrid inference router with local Ollama + cloud OpenRouter tiers (SPEC 5.7.1)
- Unified tool interface and ToolRegistry (SPEC 5.7.7)
- Dockerfiles for backend and frontend (SPEC 5e.1)
- Complete compose.yaml with health checks and profiles (SPEC 5e.2)
- Structured logging with structlog (SPEC 5e.5)
- Health endpoints `/health` and `/ready` (SPEC 5e.4)
- Backup/restore scripts (SPEC 5e.7)
- Alembic migration setup for PGLite (SPEC 5e.6)
- Skill registry with YAML validation (SPEC 2.3)
- SharedMemoryStore facade (SPEC 2.2)
- Supervisor, COO, CMO, Researcher, Engineer agents (SPEC 2.1)
- Draft-first approval workflow (SPEC 2.7.3)
- HMAC-signed semantic memory (SPEC 3b.6)
- GLiGuard prompt injection defense (SPEC 3b.8)
