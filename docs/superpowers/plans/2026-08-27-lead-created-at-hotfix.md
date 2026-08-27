# Lead created_at Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Telegram and HTTP lead ingestion reliable on SQLite when callers do not provide `created_at`.

**Architecture:** The ORM owns the timestamp through a UTC Python callable, while an Alembic migration removes the invalid SQLite server default without losing rows or indexes. A migration-backed API regression test proves both the schema change and the consumer-visible ingest behavior.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite, unittest.

**Spec:** Owner task `CORE-HOTFIX-LEAD-CREATED-AT` in the current Codex task.

## Global Constraints

- Use `datetime.now(timezone.utc)` as a callable Python default.
- Remove the `leads.created_at` server default with a SQLite-compatible migration.
- Create and verify a database backup outside Git before applying the live migration.
- Do not expose PII, secrets, database contents, or the backup artifact in logs or reports.
- Commit exactly `fix: leads created_at default` and push `main`.

---

### Task 1: Regression test and root-cause proof

**Files:**
- Create: `backend/tests/test_lead_created_at_migration.py`

**Interfaces:**
- Consumes: Alembic revision `c9f4e2a7b611`, `POST /api/leads/ingest`, `app.models.Lead`.
- Produces: a regression test that verifies no server default remains and ingest populates `created_at`.

- [x] Write a test that migrates a temporary SQLite database to the old head, preserves a row, upgrades to the new head, calls the real FastAPI route without `created_at`, and asserts a non-null timestamp.
- [x] Run the focused test before production changes and confirm it fails because SQLite evaluates `now()`.

### Task 2: Minimal model and migration fix

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/d3a6f8b1c904_lead_created_at_python_default.py`

**Interfaces:**
- Consumes: SQLAlchemy `mapped_column` defaults and Alembic batch table recreation.
- Produces: `Lead.created_at` populated by `lambda: datetime.now(timezone.utc)` and a live schema with no server default.

- [x] Replace the Lead-only server default with the Python UTC callable.
- [x] Add an upgrade that removes the default via `batch_alter_table(..., recreate="always")` on SQLite and `alter_column` elsewhere; downgrade restores the dialect-appropriate SQL default.
- [x] Re-run the focused test and confirm it passes.

### Task 3: Live migration and verification

**Files:**
- Modify outside Git: live SQLite database and a timestamped backup artifact.

**Interfaces:**
- Consumes: the new Alembic head and local services.
- Produces: migrated live schema, verified backup, and a successful disposable `ТЕСТ` ingest.

- [x] Stop the backend, make an online-safe backup outside Git, and verify both source and backup with `PRAGMA integrity_check`.
- [x] Apply `alembic upgrade head`, restart the backend, call the live ingest endpoint without `created_at`, verify the stored timestamp, then delete only that disposable test row.
- [x] Check recent bot/ingest logs using aggregate, PII-safe evidence and state any limits honestly.

### Task 4: Quality gate and delivery

**Files:**
- Verify only the files listed above and this plan.

**Interfaces:**
- Consumes: completed hotfix.
- Produces: green backend/frontend gates and the requested remote commit.

- [x] Run backend unittest, ruff, black, mypy; run frontend lint and build; verify health endpoints and frontend HTTP 200.
- [x] Review the diff for correctness, SQLite preservation, and forbidden artifacts.
- [x] Commit exactly `fix: leads created_at default`, push `main`, and verify the remote SHA.
