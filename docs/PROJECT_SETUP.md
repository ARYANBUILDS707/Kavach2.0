# KAVACH Project Setup Workflow

## Purpose and prerequisites

Future execution instructions only; setup has not been performed. Read PRD.md, DESIGN.md, ARCHITECTURE.md, API.md and AGENTS.md. Confirm D01/D02/D09 and the current approved implementation phase. Inspect existing files, manifests, scripts and user changes before scaffolding.

## Tasks

1. Establish the exact ARCHITECTURE.md folders. Preserve all documentation and CONNECTION_TEST.md.
2. Initialize React/TypeScript/Vite with routing and shared design tokens, and Python/FastAPI with validated settings and safe error/logging utilities. Pin compatible supported versions and lock dependencies.
3. Configure PostgreSQL/Redis services and same-origin frontend/API proxy in Compose. Bind internal services privately; keep model data mounts read-only. Do not install GPU infrastructure by default.
4. Add base routes and accessible page-shell components. Placeholders must say unavailable/not implemented; do not render fake incident metrics or scores.
5. Add `.env.example` using API.md names and placeholders, ignore rules for secrets/corpora/models/build output, and environment validation. Do not include bootstrapped passwords.
6. Add frontend dev/build/typecheck/lint/test scripts and backend serve/lint/typecheck/test commands. Use existing tools where present rather than replacing them.
7. Implement public liveness and startup validation. Full dependency/model readiness belongs to the later health phase; do not report unavailable models as ready.
8. Document exact startup, shutdown, migration and verification commands discovered from the created manifests.

## Scope limits

No application features, model training, external provisioning, schema beyond the current phase, real-data import, or account system unless separately assigned. Installing an unrelated UI framework or cloud SDK is not foundation work.

## Verification and completion

Run dependency installation, lint/type checks, frontend production build, backend liveness/config tests and Compose startup. Check invalid/missing secrets fail safely. Confirm browser shell renders with keyboard navigation and design tokens. Record actual commands, exit results, files created, selected versions and any environment limitation. Do not report “runnable” if startup/build was not tested.
