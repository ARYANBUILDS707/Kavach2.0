# KAVACH Feature Development Workflow

## Required task input

Identify one approved feature or implementation-plan task, its PRD requirement IDs, acceptance criteria and resolved decision dependencies. No feature is selected by this file. If input is missing, ask for the task rather than choosing an unrelated feature.

## Context and execution

Read PRD.md, DESIGN.md, ARCHITECTURE.md, DATABASE.md, API.md and AGENTS.md. Inspect relevant implementation, tests, lockfiles and current user changes. State a brief approach that reuses existing modules.

1. Map the task to routes, domain services, persistence and UI components; identify the smallest complete vertical change.
2. Update approved contracts/migrations before dependent code where the task requires a contract change. Explain any unresolved conflict before implementation.
3. Implement server validation, role/source checks and bounded data handling. Keep raw communications out of persistence/logs and client storage.
4. Implement pending, empty, success, stale, partial, conflict and error states as applicable. Reuse design tokens/components.
5. Preserve KAVACH semantics: separate synthesis/intent, null missing evidence, authorized subscriber linkage, continuous fusion and independent-risk floor.
6. Add relevant behavioral tests and run checks for the touched areas. Confirm real endpoints back the UI; isolate fixtures to tests/simulator.
7. Inspect the final diff and update affected documentation. Avoid unrelated rewrites or dependencies.

## Completion report

Report the implemented requirement, changed files, commands/tests and actual results, any migration/config steps, and remaining limitations. Distinguish a blocked model artifact from working inference. Do not mark completion when only a component or endpoint stub exists.
