# Object Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить центральную сущность Object, договор, клиента, историю
обработок и рабочий экран «Объекты».

**Architecture:** SQLAlchemy-модели и SQLite-совместимая Alembic-миграция
расширяют текущую монолитную FastAPI-схему. API вычисляет `overdue`, не хранит
его, а apartment-адрес шифрует и маскирует; React-экран использует CRUD API и
показывает карточку объекта в Drawer.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite, unittest,
React, TypeScript, Vite, Ant Design, Vitest.

**Spec:** `docs/MASTER_EKODEZ_OPERATIONAL_SYSTEM.md` и утверждённые владельцем
уточнения этапа 2 от 2026-08-23.

## Global Constraints

- Бизнес-адреса хранятся и показываются полностью; apartment-адреса маскируются.
- Адреса объектов никогда не записываются в логи.
- `overdue` возвращается API, когда `next_treatment_date < date.today()`.
- Старые Lead сохраняют `object_id = null`; бэкфилл по маскам запрещён.
- Деньги передаются строкой с двумя знаками; в Python используются Decimal.
- Новых переменных окружения и секретов нет.
- Этап 3 не начинается без команды «далее».

---

### Task 1: Schema and migration

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/c7d4e8f1a205_object_model.py`
- Create: `backend/tests/test_objects.py`

**Interfaces:**
- Produces: `Object`, `Contract`, `Client`, `Treatment`; nullable
  `Lead.object_id`.

- [ ] Write a failing integration test that creates all four models with
  `Decimal("5000.00")`, JSON risk points and a nullable legacy Lead link.
- [ ] Run `python -m unittest tests.test_objects` and confirm missing-model
  failure.
- [ ] Implement tables, relationships and the SQLite-compatible migration;
  persist Object status only as `active`, `warranty` or `inactive`.
- [ ] Run the targeted test and a clean-database `alembic upgrade head`.

### Task 2: Object service and API

**Files:**
- Create: `backend/app/objects.py`
- Modify: `backend/app/security/pii.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_objects.py`

**Interfaces:**
- Produces: `GET/POST/PATCH/DELETE /api/objects` and
  `GET /api/objects/{id}/treatments`.
- Object JSON contains `area_sqm` and contract money as two-decimal strings.

- [ ] Write failing API tests for CRUD, type/status filters, derived overdue,
  treatment history, validation and apartment masking.
- [ ] Run the targeted test and confirm 404/missing-route failures.
- [ ] Implement Pydantic contracts and service helpers; never include object
  address in structured logs.
- [ ] Run targeted tests until green, then run all backend tests.

### Task 3: Objects UI

**Files:**
- Create: `frontend/src/ObjectsPage.tsx`
- Create: `frontend/src/ObjectsPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `/api/objects` and `/api/objects/{id}/treatments`.
- Produces: navigation item, filters, create form, table and detail Drawer.

- [ ] Write a failing Vitest test that creates a gym object, verifies table
  fields and opens the detail Drawer with contract/history sections.
- [ ] Run the single test and confirm the Objects screen is missing.
- [ ] Implement the Ant Design screen with Russian labels and two-decimal
  monthly amount formatting.
- [ ] Run the single test, frontend lint and production build.

### Task 4: Acceptance and delivery

**Files:**
- Modify: `docs/MASTER_EKODEZ_OPERATIONAL_SYSTEM.md`

**Interfaces:**
- Produces: migrated local DB, two UI screenshots and one feature commit.

- [ ] Run backend unittest, ruff, black and mypy; frontend lint and build.
- [ ] Start the real local backend/frontend and verify `/health`, `/health/db`
  and HTTP 200 on port 5173.
- [ ] Through the UI create `СК Ворон`, `П. Галушина 21 к.1`, `200.00`, `gym`,
  contract `17/08`, `5000.00` RUB/month; capture table and Drawer screenshots.
- [ ] Run secret/staged-path scans, request independent code review, fix all
  Critical/Important findings and rerun affected gates.
- [ ] Commit as `feat: Object model`, push `main`, and confirm remote SHA.
