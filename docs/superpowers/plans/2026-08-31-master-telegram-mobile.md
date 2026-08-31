# Master Telegram and Mobile Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать allowlist-мастерам Telegram-сценарий сегодняшних работ с переносом, атомарным завершением, складом и автодоходом, а локальному веб-пульту — редактирование заявок и мобильные карточки 390 px.

**Architecture:** Новый чистый доменный модуль выбирает работы и выполняет перенос/завершение в одной SQLAlchemy-транзакции. Telegram poller хранит неперсональные шаги диалога в БД и переиспользует доменный модуль; ежедневный отчёт добавляет владельцу ту же allowlist-секцию. FastAPI предоставляет замаскированный PATCH Lead, а React переключает таблицы на карточки по реальному viewport.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite, unittest, React 19, TypeScript, Ant Design 6, Vitest, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-08-31-master-telegram-mobile-design.md`

## Global Constraints

- Деньги только `Decimal`; API возвращает сумму строкой с двумя знаками.
- Количество препарата только `Decimal` с точностью до трёх знаков.
- Полные PII доступны вне ПК только приватному Telegram allowlist; веб-раскрытие остаётся `request.client.host in {127.0.0.1, ::1}`.
- В логах нет PII, токенов, числовых Telegram ID и содержимого `.env`.
- Используются только существующие `TELEGRAM_BOT_TOKEN`, `OWNER_TG_ID`, `ALEXEY_TG_ID`, `PII_FERNET_KEY`, `DATABASE_URL`.
- Отменённые и выполненные заявки не входят в «Работы на сегодня».
- Утренняя сводка пока отправляется только владельцу.
- Никакого автоугадывания объекта.
- Рабочая SQLite мигрируется только после проверенной резервной копии вне Git.
- Посторонние untracked-файлы не добавляются и не изменяются.
- Этап 6 не начинается без команды «далее».

---

### Task 1: Операционная схема и SQLite-миграция

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/f6a8c2d4e701_master_workflow.py`
- Create: `backend/tests/test_master_workflow_migration.py`

**Interfaces:**
- Produces: `Lead.amount: Decimal`, `Lead.execution_date: date | None`, `Lead.performed_by: str`, `Transaction.lead_id: int | None`, `TelegramMasterDraft`.
- Produces index: `uq_transactions_lead_id` and `ix_leads_execution_date`.
- Consumes head: `e4b7c1d9a205`.

- [ ] **Step 1: Write the failing migration test**

Create a temporary SQLite database, upgrade it to `e4b7c1d9a205`, insert one legacy Lead and Transaction, then upgrade to `head`. Assert:

```python
self.assertEqual(lead_amount, Decimal("0.00"))
self.assertIsNone(execution_date)
self.assertEqual(performed_by, "Артём")
self.assertIsNone(transaction_lead_id)
self.assertIn("telegram_master_drafts", tables)
```

Insert two transactions with the same non-null `lead_id` and assert the second raises `IntegrityError`. Insert two transactions with `lead_id=NULL` and assert both succeed. Verify `PRAGMA foreign_key_check` returns no rows.

- [ ] **Step 2: Verify RED**

Run from `backend`:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_master_workflow_migration -v
```

Expected: FAIL because the columns, table and unique index do not exist.

- [ ] **Step 3: Implement the model and migration**

Use these model contracts:

```python
amount: Mapped[Decimal] = mapped_column(
    Numeric(14, 2), default=Decimal("0.00"), server_default="0.00"
)
execution_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
performed_by: Mapped[str] = mapped_column(
    String(50), default="Артём", server_default="Артём"
)
lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True)
```

Add `Index("uq_transactions_lead_id", "lead_id", unique=True)` to
`Transaction.__table_args__`. Define `TelegramMasterDraft` with `actor_key`,
`lead_id`, `action`, `step`, JSON `payload`, and Python-side UTC `updated_at`.
Add check constraints for actor/action. Use Alembic batch operations compatible
with SQLite and remove migration-only server defaults for Lead after legacy
rows are populated.

- [ ] **Step 4: Verify GREEN**

Run the same unittest; expected PASS.

---

### Task 2: Доменный сервис работ мастера

**Files:**
- Create: `backend/app/master_workflow.py`
- Modify: `backend/app/inventory.py`
- Create: `backend/tests/test_master_workflow.py`

**Interfaces:**
- Produces:

```python
def moscow_today(now: datetime | None = None) -> date: ...
def list_due_leads(session: Session, today: date) -> list[Lead]: ...
def reschedule_lead(session: Session, lead_id: int, new_date: date, today: date) -> Lead: ...
def complete_lead(
    session: Session,
    *,
    lead_id: int,
    category: str,
    performed_by: str,
    usages: list[ChemicalUsageIn],
    without_materials: bool,
    completed_at: datetime,
) -> CompletionResult: ...
```

- `CompletionResult` contains detached IDs/status only, never PII.
- Refactor inventory internals to support `create_treatment_with_inventory(..., commit=False)` while preserving the existing HTTP endpoint behavior with its default commit.

- [ ] **Step 1: Write failing due-list and reschedule tests**

Create leads for yesterday/today/tomorrow/null date and statuses `new`, `in_work`, `done`, `cancelled`. Assert literal returned IDs contain only yesterday/today `new|in_work`, overdue first. Assert today/tomorrow/+2/+7/custom future dates save; yesterday raises `InvalidExecutionDate` and leaves the original date unchanged.

- [ ] **Step 2: Verify RED**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_master_workflow.MasterWorkflowTest.test_due_leads tests.test_master_workflow.MasterWorkflowTest.test_reschedule -v
```

Expected: FAIL because `app.master_workflow` does not exist.

- [ ] **Step 3: Implement query and reschedule**

Use one ordered SQL query:

```python
select(Lead).where(
    Lead.status.in_(("new", "in_work")),
    Lead.execution_date.is_not(None),
    Lead.execution_date <= today,
).order_by(Lead.execution_date, Lead.id)
```

Reject any `new_date < today` before assigning it.

- [ ] **Step 4: Write failing completion tests**

Cover exact observable outcomes:

- two inventory rows decrement by literal Decimal amounts;
- one Treatment has `lead_id`, object, category-independent notes, executor and execution datetime;
- ChemicalUsage rows link through that Treatment to the Lead;
- Lead becomes `done` and gets `closed_at`;
- positive amount creates one `lead_auto` income with exact date/category/object/executor/lead ID;
- null category falls back to «Другие работы»;
- amount zero creates no income;
- insufficient inventory rolls back Treatment, usages, status, balance and income;
- empty usages require `without_materials=True` and still create one Treatment;
- missing object/date and invalid category/executor fail before writes;
- a second completion returns `already_done=True` and keeps one Treatment and one income.

- [ ] **Step 5: Verify RED, implement atomically, verify GREEN**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_master_workflow -v
```

Expected first: FAIL on missing completion. Implement with one final `session.commit()` and conditional inventory updates. Expected second: PASS.

---

### Task 3: Lead ingest, PATCH and compatible status completion

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/tg_poller.py` only for `_ingest` structured defaults shared with HTTP
- Create: `backend/tests/test_master_leads_api.py`
- Modify: `backend/tests/test_leads_pii.py`

**Interfaces:**
- Produces `LeadPatchIn`, extended `RawTextIn`, extended `LeadOut`.
- Produces `PATCH /api/leads/{lead_id}`.
- Preserves `POST /api/leads/{lead_id}/status` and localhost-only PII endpoint.

- [ ] **Step 1: Write failing API tests**

Use real `TestClient` with an in-memory SQLite engine. Assert:

```python
response = client.patch(
    f"/api/leads/{lead_id}",
    json={
        "amount": "2500.00",
        "execution_date": "2026-08-31",
        "category": "Плесень",
        "object_id": object_id,
        "performed_by": "Алексей",
    },
)
self.assertEqual(response.json()["amount"], "2500.00")
```

Also assert empty PATCH, three-decimal money, invalid category/executor and missing object fail with 422/404 without changes. Assert list/get responses remain masked.

Extend ingest tests: explicit `amount/execution_date` win; legacy «Сумма: 2 500,50» and `order_at` produce `2500.50` and its date; malformed amount becomes `0.00` without losing the lead.

- [ ] **Step 2: Verify RED**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_master_leads_api tests.test_leads_pii -v
```

- [ ] **Step 3: Implement minimal schemas, serialization and route**

Validate `model_fields_set` is non-empty. Use a `Decimal` field constrained to
two decimal places. Validate category with `INCOME_CATEGORIES_V1`, performer
with `("Артём", "Алексей")`, and object existence. Add
`_money_string(value: Decimal) -> str`, implemented as
`format(value.quantize(Decimal("0.01")), "f")`, and use it in `_masked_lead`.

Update compatible status logic so `done` with positive amount requires `execution_date` and creates the same unique linked income without inventory. Repeated status calls stay idempotent.

- [ ] **Step 4: Verify GREEN**

Run the same test modules; expected PASS.

---

### Task 4: Telegram state machine and full mock-TG unittest

**Files:**
- Modify: `backend/app/tg_poller.py`
- Modify: `backend/tests/test_tg_agent.py`

**Interfaces:**
- Produces `_allowed_sender_roles() -> dict[int, str]` while keeping `_allowed_sender_ids()` compatibility.
- Produces handlers for `/today`, `mw:done`, `mw:move`, category, performer, inventory, quantity, confirm and cancel.
- Consumes `TelegramMasterDraft` and `app.master_workflow`.

- [ ] **Step 1: Write failing access and list tests**

Feed `_loop` a private `/today` update from allowlist and a second update from an unknown ID. Patch only Telegram network delivery; keep database queries and PII decryption real. Assert allowlist receives cards with full synthetic phone/address and unknown sender receives none. Assert no captured stdout/stderr contains the phone, address, numeric ID, token marker or encrypted value.

- [ ] **Step 2: Write the required full failing E2E unittest**

Build a deterministic sequence of mock Telegram updates:

1. `/today`;
2. callback `mw:done:<lead_id>`;
3. category index callback;
4. performer callback;
5. inventory callback;
6. text quantity `1,250`;
7. finish callback;
8. confirm callback;
9. repeated `mw:done:<lead_id>` and confirm path.

Assert real DB state: inventory changed from `10.000` to `8.750`, Treatment references the Lead, ChemicalUsage is `1.250`, Lead is done, Transaction has exact `lead_id`, and both Treatment and Transaction counts stay one after repetition.

- [ ] **Step 3: Verify RED**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_tg_agent -v
```

Expected: FAIL because `/today` and `mw:*` handlers do not exist.

- [ ] **Step 4: Implement the state machine**

Use callback data shorter than 64 bytes. Store category by stable list index, performer by `artem|alexey`, and quantities as normalized strings. New action replaces the actor's prior draft. Text quantity/date is accepted only for the matching draft step. Add exact transfer buttons for offsets 0, 1, 2, 7 and custom `ДД.ММ.ГГГГ`.

Render PII only after sender-role resolution. On decrypt failure use existing masks. Do not include PII in `_edit_message` result summaries or logs.

- [ ] **Step 5: Verify GREEN**

Run `tests.test_tg_agent`; expected PASS.

---

### Task 5: Утренняя сводка владельцу

**Files:**
- Modify: `backend/app/reports/daily.py`
- Modify: `backend/tests/test_daily_reports.py`

**Interfaces:**
- Produces
  `format_due_leads_section(session: Session, today: date, *, reveal_pii: bool) -> list[str]`.
- Consumes `list_due_leads` and `decrypt_pii`.
- Keeps scheduler API and one-owner delivery unchanged.

- [ ] **Step 1: Write failing report tests**

For an auto report at 09:00 Moscow with owner configuration, capture the sender message and assert a `Работы на сегодня` section contains the full synthetic phone/address for yesterday/today `new|in_work`, excludes tomorrow/done/cancelled, and leaves no PII in stdout/stderr. Assert a non-allowlisted formatting call never contains full PII. Assert missing/corrupt encrypted data produces masks and the report is still sent.

- [ ] **Step 2: Verify RED**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_daily_reports -v
```

- [ ] **Step 3: Implement recipient-aware formatting**

Keep `_owner_recipient()` as the sole active recipient. Build the yesterday snapshot as before, then append today's due-work section using the same open Session before delivery. The helper accepts logical `recipient_key` and an explicitly computed allowlist decision; it never reads proxy headers or stores numeric IDs.

- [ ] **Step 4: Verify GREEN**

Run `tests.test_daily_reports`; expected PASS including existing idempotency/cooldown/catch-up tests.

---

### Task 6: Заявки — PATCH, фильтр и карточки 390 px

**Files:**
- Modify: `frontend/src/LeadsPage.tsx`
- Create: `frontend/src/LeadsPage.css`
- Modify: `frontend/src/LeadsPage.test.tsx`

**Interfaces:**
- Consumes extended Lead API and `/api/objects`.
- Produces desktop table and mobile card list selected through `window.matchMedia('(max-width: 767px)')`.

- [ ] **Step 1: Write failing UI tests**

Add complete Lead fixtures. Test opening «Редактировать», changing amount/date/category/object/executor, and assert exact PATCH JSON with money as `"2500.00"`. Assert field label is exactly «Объект».

Mock the current date and assert «Сегодня» includes overdue/today `new|in_work` and excludes tomorrow/done/cancelled/null-date. Set `matchMedia` to mobile and assert cards exist, the desktop table is absent, masks remain visible, and action buttons are accessible.

- [ ] **Step 2: Verify RED**

```powershell
pnpm test -- src/LeadsPage.test.tsx
```

- [ ] **Step 3: Implement minimal responsive UI**

Add typed edit form with `InputNumber stringMode`, native `<Input type="date">`,
and category/object/performer Selects. Fetch objects once. Use a small
`useIsMobile` hook local to the file and render only one representation. Add
CSS with `min-width: 0`, wrapping action rows, full-width controls and 44 px
mobile actions.

- [ ] **Step 4: Verify GREEN**

Run the same Vitest file; expected PASS.

---

### Task 7: Складские карточки и подпись финансовой операции

**Files:**
- Modify: `frontend/src/InventoryPage.tsx`
- Create: `frontend/src/InventoryPage.css`
- Modify: `frontend/src/InventoryPage.test.tsx`
- Modify: `frontend/src/FinancePage.tsx`
- Modify: `frontend/src/FinancePage.test.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Produces mobile-only inventory and treatment cards.
- Produces state label `transaction.object_id === null ? 'Привязать объект' : 'Изменить объект'` for both button and modal title.

- [ ] **Step 1: Write failing Inventory mobile test**

At mobile `matchMedia`, assert inventory/treatment cards render literal stock and usage values, both tables are absent, and no element has a computed/document `scrollWidth` greater than 390 in the controlled test container.

- [ ] **Step 2: Write failing Finance label tests**

For one unassigned income expect «Привязать объект». For one linked income expect «Изменить объект». Click each and assert the same PATCH `/api/transactions/{id}/object` flow remains intact.

- [ ] **Step 3: Verify RED**

```powershell
pnpm test -- src/InventoryPage.test.tsx src/FinancePage.test.tsx
```

- [ ] **Step 4: Implement and verify GREEN**

Render one desktop/mobile representation using the same viewport helper pattern. Add global `overflow-x: hidden` only after card/form widths are constrained; do not hide an overflowing component as the primary fix. Change Finance button and Modal title from the transaction state.

Run the same tests; expected PASS.

---

### Task 8: Full automated gate before live data

**Files:**
- Verify all files above.

**Interfaces:**
- Produces evidence that unit/integration/UI behavior is green before the live SQLite migration.

- [ ] **Step 1: Run targeted tests together**

Backend from `backend`:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_master_workflow_migration tests.test_master_workflow tests.test_master_leads_api tests.test_tg_agent tests.test_daily_reports -v
```

Frontend from `frontend` using the configured bundled Node/pnpm:

```powershell
pnpm test -- src/LeadsPage.test.tsx src/InventoryPage.test.tsx src/FinancePage.test.tsx
```

- [ ] **Step 2: Run full quality gate**

```powershell
# backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m ruff check app tests scripts
.venv\Scripts\python.exe -m black --check app tests scripts
.venv\Scripts\python.exe -m mypy app tests

# frontend
pnpm test
pnpm lint
pnpm build
```

Fix only failures caused by this feature through a new failing regression test. Record unrelated pre-existing whole-repository migration formatting debt separately.

---

### Task 9: Backup, live migration and acceptance

**Files:**
- Modify outside Git: working SQLite after verified backup.
- Create outside Git: timestamped backup, Playwright screenshots and acceptance JSON/Markdown evidence.

**Interfaces:**
- Produces exact created IDs and before/after control snapshot without exposing PII.

- [ ] **Step 1: Record baseline and stop backend**

Read `/health`, `/health/db`, finance/day/dashboard totals, relevant inventory quantity and counts of Lead/Treatment/Transaction. Stop only the process listening on port 8000 through the existing server stop procedure.

- [ ] **Step 2: Create and verify backup**

Resolve the SQLite path from `DATABASE_URL` without printing credentials or PII. Create an explicit timestamped `pre-master-workflow` copy outside Git. Run `PRAGMA integrity_check` on source and copy, calculate both SHA-256 values and assert equality before migration.

- [ ] **Step 3: Migrate and restart**

Run from `backend`:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

Check Alembic current is `f6a8c2d4e701`, `PRAGMA foreign_key_check` is empty, then restart backend through the hidden scheduled-task mechanism. Wait by polling `/health`, not by fixed sleep.

- [ ] **Step 4: Verify the full mock-TG scenario**

Run the single E2E unittest with mock Telegram updates against its isolated test database. It must cover the due-work card, completion wizard, linked material write-off, linked auto-income and repeated completion without duplication. Do not send a live Telegram message during acceptance.

Assert exactly one linked income, one linked material Treatment, exact Decimal stock decrement, and no duplicate after repeated completion.

- [ ] **Step 5: Run Playwright web acceptance**

Use Playwright CLI at viewport 390x844. Verify Leads «Сегодня», edit modal field «Объект», masked PII, mobile cards, Inventory cards, Finance labels for both linked/unlinked operations, and `document.documentElement.scrollWidth <= 390`. Save screenshots outside Git.

- [ ] **Step 6: Cleanup and reconcile**

Delete only IDs created by the live web acceptance, in dependency order. Re-read all baseline metrics and assert exact equality plus zero rows carrying the test marker.

---

### Task 10: Final verification, review, commit and push

**Files:**
- Stage only the plan, migration, backend/frontend production files and tests from Tasks 1–7.
- Exclude `.env`, `*.db`, backups, screenshots, attachments and unrelated untracked files.

**Interfaces:**
- Produces functional commit `feat: master workflow` and verified `origin/main` SHA.

- [ ] **Step 1: Run fresh final gate**

Repeat the complete Task 8 gate after cleanup. Then verify:

```text
/health.status=ok
/health.pii=ok
/health.reports=ok
/health/db.status=ok
127.0.0.1:5173 -> HTTP 200
```

- [ ] **Step 2: Review requirement coverage and staged diff**

Check every section of the spec against changed files and tests. Run `git diff --check`, inspect `git status --short`, and search staged paths/content for forbidden filenames and secret/token patterns. Confirm the three pre-existing untracked paths remain unmodified and unstaged.

- [ ] **Step 3: Commit and push**

```powershell
git commit -m "feat: master workflow"
git push origin main
git ls-remote origin refs/heads/main
```

The push includes the two local specification commits and the functional commit. Report local and remote SHA only after they match.

- [ ] **Step 4: Handoff**

Report status/facts/risks/HANDOFF, exact gate results, backup verification without secret paths, mock-TG and live Telegram evidence, Playwright screenshots and cleanup reconciliation. Then prepare only the design for «Договоры и акты» and wait for owner approval before implementing it. Do not start stage 6.
