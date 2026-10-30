# KAVACH Git Workflow

## Status

Procedure document, prepared 31 October 2026 and updated with the owner's decisions of the same day. The four branches below exist locally and on `origin` (all at `754a22a` when created). **GitHub branch protection, rulesets and the default branch (`main`) have not been configured or changed.** Owner decisions recorded here: `main` stays the stable release branch; `dev` is *intended* to become the GitHub default branch (not yet applied); short-lived `feature/*` branches are allowed; backend and frontend work enters `dev` only through pull requests; a minimal pytest + Ruff CI milestone (M1.1) comes before M2; `main` and `dev` are protected after CI is configured (not yet applied). A minimal CI workflow now exists in the working tree of `backend` (M1.1) but has not run on GitHub yet (see "Gates until CI exists").

## Branches

| Branch | Purpose | Who changes it |
| --- | --- | --- |
| `main` | Stable, validated releases only | Release PRs from `dev` |
| `dev` | Integration branch | PRs from `backend`, `frontend` and approved short-lived branches |
| `backend` | Long-lived backend work (API, auth, persistence, models, correlation) | Direct commits by the backend implementer |
| `frontend` | Long-lived React/TypeScript work | Direct commits by the frontend implementer |
| `feature/<milestone>-<topic>` | Short-lived branch for bounded or cross-cutting work (docs, CI, deployment, evaluation), e.g. `feature/m1-1-ci` | Allowed by owner decision; created from `dev`, merged into `dev` by PR, deleted after merge |

The directories `backend/` and `frontend/` are separate from the branches of the same name. Feature work belongs on the branch for its layer (or a `feature/*` branch); integration and release work flows through `dev`. Nothing is pushed directly to `main` or `dev`; all changes enter by pull request.

## Flow

```text
backend  ─┐
frontend ─┼─ PR ─► dev ─ release PR ─► main ─ tag
feature/* ┘
```

1. Branch from the latest `dev` when starting a milestone (`backend` and `frontend` are kept current by merging `dev` into them, below).
2. Commit small, milestone-scoped changes on the layer branch.
3. Open a PR into `dev` when the milestone's checks pass locally.
4. After review and approval, merge into `dev` with a merge commit.
5. Merge `dev` back into `backend` and `frontend` so they do not drift: `git switch backend && git merge dev` (no rebase, no force-push).
6. Release PRs go from `dev` to `main` only after [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) passes.

Merge commits (not squash, not rebase) are used for the long-lived branches so shared history stays intact and later merges stay conflict-free. Short-lived `feature/*` branches are merged by PR; the merge method for them (merge commit or squash) is still to be configured.

## Authorization rules

- **No commit, push, merge, tag or deploy without explicit user approval for that action.** Approval to implement is not approval to commit; approval to commit is not approval to push.
- Never force-push (`--force`, `--force-with-lease`) to `main`, `dev`, `backend` or `frontend`.
- Never rewrite published history, `reset --hard` shared work, or delete protected branches.
- Inspect `git status` and `git diff` before every authorized commit. Do not stage secrets, `.env` files, model binaries, audio, datasets, `.venv`, caches or lockfiles that were not intentionally generated.
- Preserve `docs/CONNECTION_TEST.md` and other unrelated files.

## Commit and PR conventions

- Commit subject in imperative, scoped form consistent with history (the baseline is `feat: initialize KAVACH backend foundation`): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`. One logical change per commit.
- Keep a commit body for the why, risks and the verification commands run.
- A PR names the milestone, links the specification sections, states what is and is not included, lists changed files, and pastes exact verification commands and results ([DEFINITION_OF_DONE.md](DEFINITION_OF_DONE.md)).
- Contract changes (API, schema, policy values) appear in the same PR as their source-of-truth document updates.

## Review and merge gates

Required before merging into `dev`:

- Definition of Done satisfied for the scope in the PR.
- Review by someone other than the author, or an explicit owner waiver recorded in the PR.
- `git diff` reviewed for secrets, private data and accidental files.
- Migrations reviewed separately; no destructive migration without explicit authorization and a recovery plan.
- No unresolved critical or high finding from the review.
- Branch up to date with `dev` (merge `dev` in first) with all checks re-run after the merge.

Required before merging `dev` into `main`: everything above, plus the release checklist, a green CI run on the exact release commit, and owner approval.

## Gates until CI exists

M1.1 adds `.github/workflows/backend-ci.yml` and `backend/uv.lock` on the `backend` branch (see [MILESTONE_TRACKER.md](MILESTONE_TRACKER.md)). The workflow runs on pull requests into `dev`/`main` and pushes to `dev`/`main`, so its first run will be the PR from `backend` into `dev`. **It has not run on GitHub yet.** Until a green run exists for a PR, the gate is local evidence pasted into the PR:

```sh
backend/.venv/bin/python -m pytest backend/tests
backend/.venv/bin/python -m ruff check backend
backend/.venv/bin/python -m ruff format --check backend
```

With `backend/uv.lock` present, the `uv run --project backend --locked` forms in CONTRIBUTING.md match CI exactly; prefer them once you have deliberately synced `backend/.venv` to the lockfile. Frontend commands are added when the frontend exists. Add integration commands for PostgreSQL/Redis when those milestones land. A local run is evidence, not a substitute for CI; mark checks that could not run as "not run".

## GitHub settings (decided in principle, not applied)

- `dev` is intended to become the default branch. **The setting has not been changed.**
- `main` and `dev` are to be protected **after CI is configured**: require a pull request and at least one approval, require the CI status checks, block force-pushes and deletions, and require branches up to date before merging into `main`. **No protection has been applied.**
- Applying either needs the owner's explicit go-ahead at the time; the earlier decision in principle is not that go-ahead.

## Rollback procedures

Order of preference, least destructive first. All are non-force operations.

1. **Bad commit already merged into `dev` or `main`:** create a revert on a branch and open a PR. For a merge commit use `git revert -m 1 <merge-sha>`. History stays intact; record the reason in the PR.
2. **Bad release:** revert the release merge on `main` via PR, or release the previous tag again by deploying that tag. Tags are never moved or deleted; publish a new patch tag.
3. **Bad migration:** prefer a forward repair migration. Do not drop data or downgrade destructively. Restore data only via the approved recovery procedure with the data-loss impact stated ([DEPLOYMENT.md](DEPLOYMENT.md), [MONITORING_MAINTENANCE.md](MONITORING_MAINTENANCE.md)). Application rollback must be schema-compatible with the migrated database.
4. **Uncommitted local mistake:** inspect with `git diff`, then restore only the specific file you own (`git restore <path>`) after confirming nothing of the user's is lost. Never `git reset --hard` or `git clean -fd` without the owner's explicit instruction.
5. **Wrong branch commit (not pushed):** create a branch at the commit, then move the original branch back only with owner approval; if already pushed, use a revert PR instead of rewriting.

Never use force-push to undo a pushed change on a protected branch.

## Open decisions

- When to apply the default-branch change and the branch protection (after M1.1, on the owner's instruction).
- Which merge method to configure in GitHub (merge commit recommended for long-lived branches; method for `feature/*` branches).
- Required reviewer count and who reviews while there is a single maintainer (an owner waiver must then be recorded per PR).
