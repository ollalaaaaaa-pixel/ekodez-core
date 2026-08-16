# Core T-Bank XLSX Import V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать двухэтапный импорт XLSX-выписок Т-Банка со строгим Decimal, детерминированной классификацией, SHA-256-идемпотентностью и сверкой оборотов кредита/дебета.

**Architecture:** Чистый `bank_import.py` парсит, нормализует, хеширует и классифицирует строки без доступа к БД. FastAPI preview возвращает серверные предложения, confirm повторно вычисляет неизменяемые результаты, валидирует только разрешённый override и атомарно сохраняет уникальные строки. Отдельный React Drawer управляет загрузкой, review-подтверждением и отчётом сверки.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL, openpyxl, unittest, React 19, TypeScript 6, Ant Design 6.

## Global Constraints

- Деньги только `Decimal`; числовая XLSX-ячейка только `Decimal(str(cell_value))`.
- Строковые суммы поддерживают `1 500 000,50` и `27,544.00`.
- SHA-256 строится из `YYYY-MM-DD|amount 0.01|trim(doc_number)|trim(counterparty_inn)`.
- Confirm повторно вычисляет hash, transfer и классификацию.
- `category_override` разрешён только серверно вычисленным `needs_review=True` строкам.
- Review-строка требует допустимый override и `review_confirmed=True`.
- Полный ИНН не выводится в логах, UI, тестовых данных или отчёте.
- Комментарий: `payment_purpose`, fallback `description`.
- Реальные XLSX не сохраняются в Git и не импортируются в production БД автоматически.
- `git add .` запрещён; `.env`, токены, offset, attachments и `backend/sample_order.txt` не индексируются.

---

### Task 1: Воспроизводимые зависимости и quality-конфигурация

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/requirements-dev.txt`
- Create: `backend/pyproject.toml`

**Interfaces:**
- Produces: runtime `openpyxl`, `python-multipart`; gates `ruff`, `black`, `mypy`, `types-openpyxl`.

- [ ] **Step 1: Создать manifests с текущими прямыми runtime-зависимостями**

`requirements.txt` фиксирует установленные версии FastAPI, Uvicorn, SQLAlchemy,
Alembic, psycopg, Pydantic, python-dotenv, а также версии `openpyxl` и
`python-multipart`, фактически разрешённые pip.

`requirements-dev.txt` содержит проверенные версии:

```text
-r requirements.txt
black==26.5.1
mypy==2.3.1
ruff==0.16.3
types-openpyxl==3.1.5.20260807
```

Новые runtime-версии: `openpyxl==3.1.5` и
`python-multipart==0.0.32`.

- [ ] **Step 2: Создать единый quality config**

```toml
[tool.black]
line-length = 88
target-version = ["py312"]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
check_untyped_defs = true
no_implicit_optional = true
warn_unused_ignores = true
files = ["app", "tests"]
```

- [ ] **Step 3: Установить зависимости и подтвердить импорты**

Run: `.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`

Run: `.\.venv\Scripts\python.exe -c "import openpyxl, multipart; print('ok')"`

Expected: `ok`, секреты не выводятся.

---

### Task 2: Decimal/date parser, BankRow и SHA-256

**Files:**
- Create: `backend/app/bank_import.py`
- Create: `backend/tests/test_bank_import.py`

**Interfaces:**
- Produces: `BankRow`, `ClassificationResult`, `parse_amount(value) -> Decimal`, `parse_date(value) -> date`, `source_hash(row) -> str`, `parse_tbank_xlsx(content: bytes) -> list[BankRow]`.

- [ ] **Step 1: Написать падающие тесты денежных форматов**

```python
self.assertEqual(parse_amount("1 500 000,50"), Decimal("1500000.50"))
self.assertEqual(parse_amount("27,544.00"), Decimal("27544.00"))
self.assertEqual(parse_amount(1500.5), Decimal("1500.50"))
```

- [ ] **Step 2: Запустить RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_import -v`

Expected: import error для отсутствующего `app.bank_import`.

- [ ] **Step 3: Реализовать immutable-типы и parsers**

```python
@dataclass(frozen=True)
class BankRow:
    operation_type: str
    operation_date: date
    doc_number: str
    amount: Decimal
    description: str
    payment_purpose: str
    counterparty_name: str
    counterparty_inn: str

@dataclass(frozen=True)
class ClassificationResult:
    kind: Literal["income", "expense"]
    category: str | None
    channel: str | None
    needs_review: bool
    is_transfer: bool
```

`parse_amount` удаляет `\u00a0`, `\u202f` и пробелы; при `,` и `.` оставляет
последний разделитель десятичным, затем quantize `0.01` с `ROUND_HALF_UP`.

- [ ] **Step 4: Написать падающие тесты workbook**

Собрать synthetic workbook через `openpyxl.Workbook`, добавить две служебные
строки, восемь обязательных заголовков и строки с Excel date и строковой датой.
Проверить `BankRow`, отсутствие обязательной колонки и повреждённые bytes.

- [ ] **Step 5: Реализовать XLSX parser**

`load_workbook(BytesIO(content), read_only=True, data_only=True)` просматривает
листы и первые строки до первого полного набора заголовков. Ошибки оборачиваются
в доменный `BankImportError` без содержимого клиентских полей.

- [ ] **Step 6: Реализовать канонический hash и mask**

```python
canonical = (
    f"{row.operation_date.isoformat()}|{row.amount:.2f}|"
    f"{row.doc_number.strip()}|{row.counterparty_inn.strip()}"
)
digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`mask_inn` оставляет не более последних четырёх цифр, остальное заменяет `*`.

- [ ] **Step 7: Запустить GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_import -v`

Expected: parser/hash tests OK.

---

### Task 3: Детерминированный Rules Engine

**Files:**
- Modify: `backend/app/bank_import.py`
- Modify: `backend/tests/test_bank_import.py`

**Interfaces:**
- Consumes: `BankRow`.
- Produces: `classify_transaction(row: BankRow) -> ClassificationResult`, `transaction_comment(row: BankRow) -> str`.

- [ ] **Step 1: Написать table-driven RED для всех веток credit**

Литеральные ожидания покрывают transfer/return, клещи, химчистку, дератизацию,
дезинфекцию, дезинсекцию, непустой ИНН и fallback. Для порядка добавить строку,
где одновременно встречаются `клещ` и `дезинсекция`, ожидая клещевую категорию.

- [ ] **Step 2: Написать table-driven RED для всех веток debit**

Покрыть transfer, МЕДИЛИС, Дез средства, ЕНС, ФНС, взносы, ТБанк, Комиссия,
SMS, обслуживание и fallback с `category=None, needs_review=True`.

- [ ] **Step 3: Проверить RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_import -v`

Expected: attribute error для отсутствующего классификатора.

- [ ] **Step 4: Реализовать правила в утверждённом порядке**

Кредит проверяет transfer/return по назначению первым. Дебет проверяет transfer
первым, затем отдельные поля согласно спецификации. Неизвестный тип операции
вызывает `BankImportError("unsupported operation type")`.

- [ ] **Step 5: Реализовать comment fallback и GREEN**

```python
def transaction_comment(row: BankRow) -> str:
    return row.payment_purpose.strip() or row.description.strip()
```

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_import -v`

Expected: все rules tests OK.

---

### Task 4: Transaction migration и expense seeds

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/e9b7c4d2a610_tbank_import_fields.py`
- Create: `backend/tests/test_bank_models.py`

**Interfaces:**
- Produces: `Transaction.source_hash`, `doc_number`, `counterparty_inn`, `import_batch_id`, `source_filename`, `needs_review`.

- [ ] **Step 1: Написать RED для ORM metadata**

```python
columns = Transaction.__table__.c
self.assertEqual(columns.source_hash.type.length, 64)
self.assertTrue(columns.source_hash.nullable)
self.assertEqual(columns.doc_number.type.length, 50)
self.assertEqual(columns.counterparty_inn.type.length, 20)
self.assertEqual(columns.source_filename.type.length, 255)
self.assertFalse(columns.needs_review.nullable)
```

- [ ] **Step 2: Проверить RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_models -v`

Expected: missing column failure.

- [ ] **Step 3: Добавить typed ORM columns**

Использовать `sqlalchemy.Uuid` и `uuid.UUID` для batch id. `source_hash` nullable
и имеет unique index; `needs_review` имеет Python default False.

- [ ] **Step 4: Создать Alembic migration**

Revision `e9b7c4d2a610`, down revision `c4e8a1b7d903`. Upgrade добавляет поля,
unique index `ix_transactions_source_hash`, server default false и idempotent
insert двух новых expense categories через SQL. Downgrade удаляет только seeds,
созданные этой миграцией, индекс и поля.

- [ ] **Step 5: Запустить GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_models -v`

Expected: model tests OK.

---

### Task 5: Preview и confirm API

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_bank_api.py`

**Interfaces:**
- Consumes: bank service, ORM fields, income and expense catalogs.
- Produces: `POST /api/bank/preview`, `POST /api/bank/confirm`, reconciliation response.

- [ ] **Step 1: Написать RED preview через TestClient**

Создать synthetic XLSX в памяти, отправить multipart и проверить Decimal strings,
masked INN, comment fallback, category, channel, flags и hash. Отдельно проверить
invalid XLSX HTTP 400.

- [ ] **Step 2: Написать RED confirm validation**

Проверить HTTP 422 для tampered hash, review без `review_confirmed`, отсутствующего
override, override у уверенной строки и категории вне утверждённого справочника.

- [ ] **Step 3: Написать RED idempotency и reconciliation**

Synthetic rows должны давать:

```python
self.assertEqual(first["imported_income_amount"], "100000.00")
self.assertEqual(first["imported_expense_amount"], "50000.00")
self.assertEqual(first["excluded_credit_amount"], "497562.80")
self.assertEqual(first["excluded_debit_amount"], "547562.66")
self.assertEqual(first["statement_credit_total"], "597562.80")
self.assertEqual(first["statement_debit_total"], "597562.66")
self.assertTrue(first["credit_reconciled"])
self.assertTrue(first["debit_reconciled"])
```

Повторный confirm ожидает imported 0, duplicates 2, duplicate sums
`100000.00/50000.00`, те же statement totals и оба reconciliation true.

- [ ] **Step 4: Проверить RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_bank_api -v`

Expected: route 404 или missing DTO.

- [ ] **Step 5: Реализовать preview DTO и endpoint**

Использовать `UploadFile`/`File`, проверить расширение `.xlsx`, прочитать bytes,
вызвать parser/classifier. `counterparty_inn_masked` выводится отдельно; endpoint
ничего не логирует из строк.

- [ ] **Step 6: Реализовать confirm DTO, revalidation и category checks**

Confirm reconstructs `BankRow`, compares recomputed hash, classifies, validates
review. Income override проверяется по `INCOME_CATEGORIES_V1`, expense — по
активным `ExpenseCategory`. Все preview rows, включая transfer, принимаются и
участвуют в totals.

- [ ] **Step 7: Реализовать атомарное сохранение и duplicate savepoints**

Для каждой сохраняемой строки сначала искать `source_hash`. Insert/flush выполнять
в `session.begin_nested()`; `IntegrityError` unique conflict откатывает только
savepoint и увеличивает duplicate count. Внешний transaction коммитится один раз.

- [ ] **Step 8: Реализовать Decimal reconciliation**

Все восемь сумм начинаются с `Decimal("0.00")`, увеличиваются по direction/status,
quantize `0.01`; booleans сравнивают точные Decimal equality.

- [ ] **Step 9: Запустить полный backend GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: все старые и новые tests OK.

---

### Task 6: React Drawer предпросмотра и отчёта

**Files:**
- Create: `frontend/src/BankImportDrawer.tsx`
- Create: `frontend/src/BankImportDrawer.css`
- Modify: `frontend/src/FinancePage.tsx`

**Interfaces:**
- Consumes: preview array, confirm request/response, `/api/expense-categories`.
- Produces: upload button, review workflow, masked UI, reconciliation report.

- [ ] **Step 1: Создать строгие frontend types**

`BankPreviewRow` включает raw immutable fields, masked INN, classification and
hash. UI state adds `category_override` and `review_confirmed` without mutating
raw values. `ConfirmResult` включает counts, batch id, eight amount strings and
two reconciliation booleans.

- [ ] **Step 2: Реализовать upload/preview state machine**

AntD `Upload` accepts `.xlsx`, `beforeUpload={() => false}`. Explicit action
builds `FormData`, POSTs preview, loads expense categories in parallel and stores
all rows. Transfers remain in state but table data filters them out.

- [ ] **Step 3: Реализовать review table**

Колонки: date, kind, counterparty + masked INN, amount, category Select/read-only,
channel, comment, confirmation. Yellow class for review rows. Category change
clears confirmation; explicit 44px `Подтвердить` sets it true.

- [ ] **Step 4: Реализовать confirm and report**

Button disabled if any visible review row lacks override or confirmation. Payload
sends all rows. Success notification includes counts; Drawer shows reconciliation
cards for imported, duplicate, excluded and statement amounts with green/red
status for credit/debit equality. Close triggers `onImported()`.

- [ ] **Step 5: Интегрировать в FinancePage**

Добавить кнопку `Импорт выписки (Т-Банк)` над analytics/operations и передать
callback, который повторно вызывает текущий `load()` и reload analytics via a
monotonic refresh key.

- [ ] **Step 6: Добавить адаптивные styles**

Desktop Drawer width около 1100, mobile `100%`; table `scroll={{x: 1100}}`, touch
targets >=44px, yellow review background, reconciliation grid 2→1 columns.

- [ ] **Step 7: Проверить frontend**

Run: `npm run lint`

Run: `npm run build`

Workdir: `frontend`

Expected: both exit 0.

---

### Task 7: Миграция, реальная preview-проверка и полный gate

**Files:**
- Modify only for defects: files from Tasks 1–6.
- Create outside Git: synthetic XLSX and screenshots under `C:\Users\user\Desktop\ЭкоДез\_runtime_docs\`.

**Interfaces:**
- Consumes: complete feature.
- Produces: acceptance evidence, no automatic production import of real rows.

- [ ] **Step 1: Применить migration**

Run: `.\.venv\Scripts\python.exe -m alembic upgrade head`

Expected: `e9b7c4d2a610 (head)`.

- [ ] **Step 2: Перезапустить backend/frontend безопасно**

Определить listeners 8000/5173, остановить только Ekodez Core, запустить hidden
процессы с отдельными stdout/stderr logs.

Expected: `/health=ok`, frontend 200, log `TG poller: started`.

- [ ] **Step 3: Выполнить synthetic browser/API scenario**

Загрузить synthetic XLSX с turnover `597562.80/597562.66`, подтвердить review,
проверить импорт/отсечение/reconciliation и повторный import duplicates. После
доказательства удалить только созданные synthetic DB rows по batch id безопасным
одноразовым скриптом; delete endpoint не добавлять.

- [ ] **Step 4: Найти реальную выписку read-only**

Просканировать доступные `.xlsx` только по обязательным headers через parser. Если
ровно один файл подходит, вызвать preview без confirm, не выводить PII и сравнить
credit/debit totals с `597562.80/597562.66`. Если подходящего файла нет либо их
несколько, статус `UNRESOLVED` с точной причиной.

- [ ] **Step 5: Запустить полный gate свежим состоянием**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\black.exe --check app tests
.\.venv\Scripts\mypy.exe app tests
npm run lint
npm run build
```

Expected: every command exit 0. Compileall uses an external pycache path if
Windows ACL blocks existing `__pycache__`.

---

### Task 8: Безопасный commit, push и регламентный отчёт

**Files:**
- Stage only files created/modified in Tasks 1–6 plus migration and tests.

**Interfaces:**
- Produces: commit and push to `origin/main`; status/facts/risks/HANDOFF TO QWEN.

- [ ] **Step 1: Security and scope audit**

Run `git diff --check`, exact `git status`, ignored-path checks and secret-pattern
count without printing matching contents. Confirm source XLSX and synthetic files
are outside Git.

- [ ] **Step 2: Stage exact paths only**

Use `git add -- <explicit paths>`; never `git add .`. Verify
`git diff --cached --name-status` contains only intended files.

- [ ] **Step 3: Commit and push**

```text
git commit -m "feat: add T-Bank XLSX import with openpyxl, rules engine and SHA-256 idempotency"
git push origin main
```

- [ ] **Step 4: Report**

Report `COMPLETE/PARTIAL/BLOCKED`, changed files, actual gate counts/exit codes,
migration, services, synthetic turnover reconciliation, honest real-statement
status, Git commits/status, security confirmation, risks and `HANDOFF TO QWEN`.
