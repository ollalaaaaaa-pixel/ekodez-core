# Daily Telegram Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ежедневно отправлять владельцу безопасную управленческую сводку за вчера с идемпотентным auto-режимом, localhost-only ручным запуском и наблюдаемым статусом.

**Architecture:** Изолированный модуль `reports/daily.py` собирает Decimal-метрики, форматирует сообщение и фиксирует результат доставки по логическому получателю. В однопроцессном локальном backend отправки сериализуются, чтобы параллельные запросы не обходили auto-idempotency и cooldown. `reports/scheduler.py` содержит чистые функции временного окна и один daemon-thread, который напрямую вызывает сервис в 09:00–12:59 по Москве. FastAPI только связывает startup, health и localhost-only endpoint.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite, stdlib `zoneinfo`/`threading`, unittest.

**Spec:** `docs/superpowers/specs/2026-08-26-daily-telegram-summary-design.md`

## Global Constraints

- Получатель этапа 5 — только `OWNER_TG_ID`; `ALEXEY_TG_ID` не использовать.
- Не добавлять переменные окружения или секреты.
- Деньги считать через `Decimal` и форматировать с двумя знаками.
- Не включать PII, адреса, ИНН, токены или Telegram ID в сообщение, логи и отчёт о выполнении.
- Ручной endpoint проверяет только `request.client.host`; proxy-заголовки игнорируются.
- Шедулер вызывает Python-сервис напрямую, не через HTTP.
- Этап 6 не начинать.

---

### Task 1: Модель закрытия заявки и аудит отправок

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/b5e1d3f7a824_daily_reports.py`
- Create: `backend/tests/test_daily_reports.py`

**Interfaces:**
- Produces: `Lead.closed_at: datetime | None`.
- Produces: `SentReport(id, report_date, report_type, recipient_key, status, sent_at, created_at)`.
- Produces: уникальный частичный индекс успешного `auto` по `(report_date, recipient_key)`.

- [ ] **Step 1: Write the failing model and migration tests**

```python
def test_done_status_sets_closed_at_and_reopening_clears_it():
    created = client.post("/api/leads/ingest", json={"text": "id сделки: 501"}).json()
    closed = client.post(f"/api/leads/{created['id']}/status", json={"status": "done"})
    assert closed.status_code == 200
    with Session(engine) as session:
        assert session.get(Lead, created["id"]).closed_at is not None
    client.post(f"/api/leads/{created['id']}/status", json={"status": "in_work"})
    with Session(engine) as session:
        assert session.get(Lead, created["id"]).closed_at is None
```

```python
def test_migration_preserves_legacy_lead_and_adds_sent_reports():
    command.upgrade(config, "a4d9c2e7f613")
    # Insert one Lead, upgrade to head, then assert the row remains,
    # closed_at is nullable and sent_reports has the partial unique index.
```

- [ ] **Step 2: Run tests and observe the missing model fields**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports -v`

Expected: FAIL because `Lead.closed_at`, `SentReport` and the migration do not exist.

- [ ] **Step 3: Add the SQLAlchemy models and SQLite-compatible migration**

```python
class SentReport(Base):
    __tablename__ = "sent_reports"
    __table_args__ = (
        CheckConstraint("report_type IN ('auto', 'manual')"),
        CheckConstraint("status IN ('sent', 'failed')"),
        Index(
            "uq_sent_reports_auto_recipient_date",
            "report_date",
            "recipient_key",
            unique=True,
            sqlite_where=text("report_type = 'auto' AND status = 'sent'"),
            postgresql_where=text("report_type = 'auto' AND status = 'sent'"),
        ),
    )
```

Use `op.add_column("leads", sa.Column("closed_at", sa.DateTime(), nullable=True))`, create `sent_reports`, checks, normal indexes and the partial unique index. Downgrade removes the table before `closed_at`.

- [ ] **Step 4: Update the lead status transition**

In `set_lead_status`, retain the existing timestamp on repeated `done`, set it on the first transition to `done`, and set it to `None` when moving to any other status.

- [ ] **Step 5: Run the targeted tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports -v`

Expected: model, transition and migration tests PASS.

---

### Task 2: Pure daily snapshot and safe Telegram text

**Files:**
- Create: `backend/app/reports/__init__.py`
- Create: `backend/app/reports/daily.py`
- Modify: `backend/tests/test_daily_reports.py`

**Interfaces:**
- Produces: `ReportSnapshot` dataclass.
- Produces: `build_daily_snapshot(session: Session, report_date: date) -> ReportSnapshot`.
- Produces: `format_daily_report(snapshot: ReportSnapshot) -> str`.

- [ ] **Step 1: Write a failing aggregation test with hand-calculated values**

Seed confirmed income `1000.10`, confirmed expense `250.05`, an unconfirmed income excluded from totals, one new Lead, one Lead with `closed_at`, one `needs_review` transaction, eleven overdue objects and eleven low-stock inventory rows. Assert:

```python
assert snapshot.revenue == Decimal("1000.10")
assert snapshot.expenses == Decimal("250.05")
assert snapshot.profit == Decimal("750.05")
assert snapshot.margin_pct == Decimal("75.00")
assert snapshot.new_leads == 1
assert snapshot.closed_leads == 1
assert snapshot.disputed_operations == 1
```

Assert the message contains `1 000.10 ₽`, `250.05 ₽`, both lead counts, at most ten object and inventory details, and contains none of the seeded phone, address or token marker strings.

- [ ] **Step 2: Run the test and observe the missing report module**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailySnapshotTest -v`

Expected: FAIL importing `app.reports.daily`.

- [ ] **Step 3: Implement Decimal queries and dataclasses**

Define immutable `OverdueObject`, `LowStockItem` and `ReportSnapshot`. Use inclusive `operation_date == report_date`, datetime half-open bounds for Lead timestamps, `LOW_STOCK_RATIO`, and `Decimal("0.01")` quantization with `ROUND_HALF_UP`.

- [ ] **Step 4: Implement deterministic formatting**

Use headings `Сводка ЭКОДЕЗ за DD.MM.YYYY`, `Финансы`, `Заявки`, `Контроль`, include profit and margin percent, never addresses, and truncate each detail list to ten items plus `… и ещё N`.

- [ ] **Step 5: Run the snapshot tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailySnapshotTest -v`

Expected: PASS.

---

### Task 3: Delivery, recipient status and manual cooldown

**Files:**
- Modify: `backend/app/tg_poller.py`
- Modify: `backend/app/reports/daily.py`
- Modify: `backend/tests/test_daily_reports.py`

**Interfaces:**
- Produces: `send_message(token: str, chat_id: int, text: str) -> bool` public wrapper.
- Produces: `ReportsConfigurationError`, `ManualReportCooldown`, `TelegramDeliveryError`.
- Produces: `send_daily_report(engine: Engine, report_type: Literal['auto', 'manual'], now: datetime, sender: Callable[[str, int, str], bool] = send_message) -> SentReport`.
- Produces: `successful_auto_exists(session, report_date, recipient_key='owner') -> bool`.

- [ ] **Step 1: Write failing delivery tests**

Cover successful owner delivery, missing token/owner, invalid owner ID, failed sender producing `status=failed`, a second auto returning the existing successful row without invoking sender, manual at 59 seconds raising `ManualReportCooldown`, and manual at exactly 60 seconds succeeding.

- [ ] **Step 2: Run and observe missing delivery functions**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailyDeliveryTest -v`

Expected: FAIL because delivery interfaces are missing.

- [ ] **Step 3: Implement owner-only recipient resolution and attempt rows**

Resolve only `OWNER_TG_ID` to logical key `owner`. Do not read `ALEXEY_TG_ID`. Store no numeric Telegram ID in `sent_reports`. Insert `sent` or `failed` after every sender result and commit it. For auto, check a successful row before formatting/sending.

- [ ] **Step 4: Implement exact 60-second cooldown**

Query the latest `manual/owner/sent` row. Raise `ManualReportCooldown(retry_after_seconds)` only while elapsed time is strictly less than 60 seconds.

- [ ] **Step 5: Run delivery tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailyDeliveryTest -v`

Expected: PASS.

---

### Task 4: Direct scheduler and degraded health

**Files:**
- Create: `backend/app/reports/scheduler.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_daily_reports.py`
- Modify: `backend/tests/test_tg_poller_logging.py`

**Interfaces:**
- Produces: `MOSCOW_TZ = ZoneInfo('Europe/Moscow')`.
- Produces: `within_catchup_window(now: datetime) -> bool` (09:00–12:59 с допуском на пробуждение после 12:00).
- Produces: `next_check_at(now: datetime) -> datetime` returning 09:00, 10:00, 11:00, 12:00 or next-day 09:00.
- Produces: `run_due_auto(engine: Engine, now: datetime) -> bool`.
- Produces: `start_report_scheduler(engine: Engine) -> None`, `reports_status() -> Literal['ok', 'degraded']`.

- [ ] **Step 1: Write failing pure-time tests**

Assert startup at 08:59 is outside the window and schedules 09:00; 09:00, 10:37, 12:00 and 12:00:01 are inside; 13:00 is outside and schedules next-day 09:00. Patch `send_daily_report` to verify catch-up calls the service directly once and skips when a successful auto exists.

- [ ] **Step 2: Write failing startup and health tests**

Without token/owner, assert no thread starts, stderr contains a structured `reports_scheduler_degraded` warning without environment values, and `/health` reports `reports=degraded`. With configuration and a patched thread, assert it starts once and health is `ok`.

- [ ] **Step 3: Run scheduler tests and observe missing interfaces**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailySchedulerTest tests.test_tg_poller_logging -v`

Expected: FAIL.

- [ ] **Step 4: Implement scheduler loop**

At thread start, immediately call `run_due_auto` when inside the catch-up window. Otherwise wait until `next_check_at`; after every wake, call `run_due_auto`. Catch all loop exceptions, emit structured warning metadata only, and continue.

- [ ] **Step 5: Wire startup and health**

The existing startup hook calls `start_poller(engine)` and `start_report_scheduler(engine)`. Extend `/health` with `reports_status()` without changing global `status`.

- [ ] **Step 6: Run scheduler and regression tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports tests.test_tg_poller_logging -v`

Expected: PASS.

---

### Task 5: Localhost-only manual endpoint

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_daily_reports.py`

**Interfaces:**
- Produces: `POST /api/reports/daily/send`.
- Produces: response `{status, report_date, sent_at, recipient_key}`.

- [ ] **Step 1: Write failing endpoint tests**

Use `TestClient(..., client=('198.51.100.10', 51000))` with `X-Forwarded-For: 127.0.0.1` and assert 403 and no sender call. Use localhost and patched delivery for 200. Assert 429 with `Retry-After` during cooldown, 503 for missing configuration, and 502 for Telegram failure.

- [ ] **Step 2: Run endpoint tests and observe 404**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailyReportApiTest -v`

Expected: FAIL because the endpoint is absent.

- [ ] **Step 3: Implement endpoint and response schema**

Read only `request.client.host`, map service exceptions to the specified HTTP statuses, set `Retry-After` to the integer remaining seconds, and never return formatted report text.

- [ ] **Step 4: Run endpoint tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_daily_reports.DailyReportApiTest -v`

Expected: PASS.

---

### Task 6: Migration, complete verification and live acceptance

**Files:**
- Verify all modified files.
- Store backups/screenshots outside Git under `C:\D\Экодез\backups` and `C:\D\Экодез\acceptance`.

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: verified production migration, Telegram delivery evidence and published commit.

- [ ] **Step 1: Stop services and back up SQLite**

Copy `backend/ekodez.db` to `C:\D\Экодез\backups\ekodez-pre-daily-report-<timestamp>.db`, compare SHA-256, and do not run Alembic unless hashes match.

- [ ] **Step 2: Upgrade and verify schema/data counts**

Run: `.venv\Scripts\python.exe -m alembic upgrade head`

Verify head `b5e1d3f7a824`, nullable `leads.closed_at`, `sent_reports` indexes and unchanged Lead count.

- [ ] **Step 3: Run the complete gate**

Run:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -m ruff check app tests alembic\versions\b5e1d3f7a824_daily_reports.py
.venv\Scripts\python.exe -m black --check app tests alembic\versions\b5e1d3f7a824_daily_reports.py
.venv\Scripts\python.exe -m mypy app
pnpm.cmd lint
pnpm.cmd build
```

Expected: every command exits 0; warnings are recorded separately from failures.

- [ ] **Step 4: Restart final services and verify health**

Assert `/health.status=ok`, `/health.pii=ok`, `/health.reports=ok`, `/health/db.status=ok`, Telegram state follows the configured token, and frontend returns HTTP 200.

- [ ] **Step 5: Reconcile yesterday with dashboard and send live report**

Read `/api/analytics/dashboard?start_date=<yesterday>&end_date=<yesterday>` and the pure report snapshot, comparing revenue, expenses and margin percent exactly as Decimal strings. Execute one localhost `POST /api/reports/daily/send`; assert HTTP 200 and one successful `manual/owner` row without reading or printing the token or Telegram ID.

- [ ] **Step 6: Capture recipient evidence**

Capture the received Telegram message in the owner's available UI. If Telegram UI is unavailable to automation, report screenshot evidence as `UNRESOLVED` and request the owner's screenshot; never fabricate a mock screenshot as production evidence.

- [ ] **Step 7: Review, secret scan, commit and push**

Run independent code review, fix Critical/Important findings, stage only source/tests/docs/migration, verify no `.env`, `*.db`, identifiers or tokens are staged, then:

```powershell
git commit -m "feat: daily telegram summary"
git push origin main
git ls-remote origin refs/heads/main
```

Confirm local SHA equals remote SHA and the working tree is clean. Do not start stage 6.
