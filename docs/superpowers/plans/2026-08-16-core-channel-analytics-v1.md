# Core Channel Analytics V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить фиксированный канал к доходам и показать в финансах выручку, количество операций, средний чек и долю каждого канала за быстрый период.

**Architecture:** Фиксированные значения каналов живут в одном backend-модуле и проверяются на границе API; `Transaction.channel` остаётся nullable для старых и неразмеченных записей. Аналитика агрегируется через SQLAlchemy и возвращает Decimal-метрики, а React-экраны используют Select в форме дохода и отдельный адаптивный блок в финансах.

**Tech Stack:** Python 3, FastAPI, Pydantic, SQLAlchemy, Alembic, unittest, React 19, TypeScript 6, Ant Design 6, dayjs, Vite.

## Global Constraints

- Каналы: `Яндекс | 2ГИС | Авито | ВК | Сарафан | Прочее`.
- `Прочее` используется для доходов вне каналов, включая юридических лиц по счёту.
- `channel=null` в аналитике группируется как `Не указан`.
- В аналитику входят только записи `kind="income"` в включительном диапазоне дат.
- Денежные расчёты выполняются через `Decimal`, JSON-значения округляются до 2 знаков.
- Не добавлять динамический справочник каналов, custom DatePicker или автоматическое распознавание канала.
- Не коммитить `.env`, токены, вложения, `tg_offset.json` и `backend/sample_order.txt`.
- Не использовать `git add .`; индексировать только перечисленные целевые файлы.

---

### Task 1: Backend-модель каналов и миграция

**Files:**
- Create: `backend/app/channels.py`
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/c4e8a1b7d903_transaction_channel.py`
- Test: `backend/tests/test_channel_analytics_api.py`

**Interfaces:**
- Produces: `CHANNELS: tuple[str, ...]` и `Transaction.channel: Mapped[str | None]`.
- Consumes: Alembic revision `a8f5c3d1e902`.

- [ ] **Step 1: Написать падающий тест списка каналов и поля модели**

```python
def test_channels_are_the_owner_approved_fixed_values(self):
    self.assertEqual(
        CHANNELS,
        ("Яндекс", "2ГИС", "Авито", "ВК", "Сарафан", "Прочее"),
    )

def test_transaction_channel_is_nullable(self):
    column = Transaction.__table__.c.channel
    self.assertTrue(column.nullable)
    self.assertEqual(column.type.length, 50)
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_channel_analytics_api -v`

Expected: `ERROR` из-за отсутствующего `app.channels` или `Transaction.channel`.

- [ ] **Step 3: Добавить фиксированный модуль каналов**

```python
"""Утверждённые каналы привлечения Ekodez Core."""

CHANNELS = ("Яндекс", "2ГИС", "Авито", "ВК", "Сарафан", "Прочее")
```

- [ ] **Step 4: Добавить nullable-поле ORM**

```python
channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 5: Создать миграцию**

```python
revision = "c4e8a1b7d903"
down_revision = "a8f5c3d1e902"

def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("channel", sa.String(length=50), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("transactions", "channel")
```

- [ ] **Step 6: Запустить тест модели**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_channel_analytics_api -v`

Expected: тесты списка и nullable-поля проходят; тесты ещё не реализованного API могут оставаться красными.

---

### Task 2: Валидация канала и API аналитики

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_channel_analytics_api.py`
- Modify: `backend/tests/test_day_api.py`

**Interfaces:**
- Consumes: `CHANNELS`, `Transaction.channel`.
- Produces: `TransactionIn.channel`, `TransactionOut.channel`, `DayEntryIn.channel`, helper `_transaction_channel(kind: str, channel: str | None) -> str | None` и `GET /api/analytics/channels`.

- [ ] **Step 1: Написать падающие тесты записи канала**

```python
def test_income_accepts_approved_channel(self):
    row = main.create_day_entry(main.DayEntryIn(
        kind="income", category="Химчистка", amount=Decimal("5000.00"),
        channel="2ГИС", date=date(2026, 8, 16),
    ))
    self.assertEqual(row.channel, "2ГИС")

def test_income_rejects_unknown_channel(self):
    with self.assertRaises(HTTPException) as caught:
        main.create_day_entry(main.DayEntryIn(
            kind="income", category="Химчистка", amount=Decimal("5000.00"),
            channel="Телеграм", date=date(2026, 8, 16),
        ))
    self.assertEqual(caught.exception.status_code, 422)

def test_expense_forces_channel_to_null(self):
    row = main.create_day_entry(main.DayEntryIn(
        kind="expense", category="Еда", amount=Decimal("500.00"),
        channel="Авито", date=date(2026, 8, 16),
    ))
    self.assertIsNone(row.channel)

def test_direct_transaction_api_rejects_unknown_income_channel(self):
    with self.assertRaises(HTTPException) as caught:
        main.create_transaction(main.TransactionIn(
            operation_date=date(2026, 8, 16), amount=Decimal("5000.00"),
            kind="income", channel="Телеграм",
        ))
    self.assertEqual(caught.exception.status_code, 422)
```

- [ ] **Step 2: Написать падающий агрегатный тест**

Создать в in-memory SQLite четыре дохода текущего периода: `Авито 5000`, `Авито 7000`, `Сарафан 10000`, `channel=None 3000`, а также расход и доход за пределами периода. Проверить:

```python
result = main.channel_analytics(date(2026, 8, 1), date(2026, 8, 31))
self.assertEqual(result["period_total"], Decimal("25000.00"))
self.assertEqual(result["channels"][0], {
    "channel": "Авито",
    "total_amount": Decimal("12000.00"),
    "count": 2,
    "avg_check": Decimal("6000.00"),
    "share_percent": Decimal("48.00"),
})
self.assertIn("Не указан", [row["channel"] for row in result["channels"]])
```

- [ ] **Step 3: Запустить новые тесты и проверить ожидаемое падение**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_channel_analytics_api backend.tests.test_day_api -v`

Expected: `FAIL` или `ERROR`, потому что DTO и endpoint ещё не принимают канал.

- [ ] **Step 4: Расширить DTO и запись операций**

```python
class TransactionIn(BaseModel):
    channel: str | None = None

class TransactionOut(BaseModel):
    channel: str | None

class DayEntryIn(BaseModel):
    channel: str | None = None
```

Добавить единый helper и использовать его и в `create_transaction`, и в
`create_day_entry`, чтобы прямой API не обходил проверку:

```python
def _transaction_channel(kind: str, channel: str | None) -> str | None:
    if kind != "income":
        return None
    if channel is not None and channel not in CHANNELS:
        raise HTTPException(status_code=422, detail="bad channel")
    return channel
```

При создании ORM-строки передавать
`channel=_transaction_channel(payload.kind, payload.channel)`.

- [ ] **Step 5: Добавить модели ответа и endpoint**

```python
class ChannelAnalyticsItem(BaseModel):
    channel: str
    total_amount: Decimal
    count: int
    avg_check: Decimal
    share_percent: Decimal

class ChannelAnalyticsOut(BaseModel):
    period_total: Decimal
    channels: list[ChannelAnalyticsItem]
```

Получить сгруппированные строки через `select(Transaction.channel, func.sum(...), func.count(...))`, нормализовать `None`/пустые строки в `Не указан`, объединить такие группы в Python через `Decimal`, вычислить средний чек и процент с `quantize(Decimal("0.01"))`, отсортировать по `(-total_amount, channel)`.

- [ ] **Step 6: Проверить диапазон дат и пустой ответ**

Добавить тест `start_date > end_date` с ожиданием HTTP 422 и тест пустого периода:

```python
self.assertEqual(
    main.channel_analytics(date(2026, 7, 1), date(2026, 7, 31)),
    {"period_total": Decimal("0.00"), "channels": []},
)
```

- [ ] **Step 7: Запустить backend-тесты**

Run: `backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v`

Expected: все тесты `OK`, включая сумму, count, avg, share, null-группу, фильтр дат и сортировку.

---

### Task 3: Выбор канала в форме дохода

**Files:**
- Modify: `frontend/src/DayPage.tsx`
- Modify: `frontend/src/DayPage.css`

**Interfaces:**
- Consumes: `POST /api/day/entry` с `channel: string | null`.
- Produces: необязательный Select канала только для доходных desktop- и mobile-форм.

- [ ] **Step 1: Расширить frontend-черновик и фиксированный список**

```tsx
type Draft = {
  kind: Kind
  category: string
  channel: string
  amount: number | null
  comment: string
}

const CHANNELS = ['Яндекс', '2ГИС', 'Авито', 'ВК', 'Сарафан', 'Прочее'] as const
const emptyDraft = (kind: Kind): Draft => ({
  kind, category: '', channel: '', amount: null, comment: '',
})
```

- [ ] **Step 2: Передавать канал в POST**

```tsx
body: JSON.stringify({
  kind: draft.kind,
  category: draft.category,
  channel: draft.kind === 'income' ? draft.channel || null : null,
  amount: draft.amount,
  comment: draft.comment || null,
  entered_by: enteredBy,
  date: selectedDate,
})
```

- [ ] **Step 3: Добавить Select в обе доходные формы**

```tsx
{draft.kind === 'income' && (
  <Select
    className="day-channel-select"
    allowClear
    placeholder="Канал (необязательно)"
    value={draft.channel || undefined}
    onChange={(channel) => setDraft({ ...draft, channel: channel ?? '' })}
    options={CHANNELS.map((channel) => ({ value: channel, label: channel }))}
  />
)}
```

Повторить тот же Select для `mobileDraft`; в расходной форме элемент не рендерить.

- [ ] **Step 4: Сохранить мобильные тач-таргеты**

```css
.day-channel-select { min-width: 190px; }
@media (max-width: 767px) {
  .day-entry-form > .day-channel-select { width: 100%; }
  .day-channel-select { min-height: 48px; }
}
```

- [ ] **Step 5: Запустить frontend lint и build**

Run: `npm run lint`

Run: `npm run build`

Workdir: `frontend`

Expected: обе команды завершаются exit code 0.

---

### Task 4: Блок «По каналам» на экране финансов

**Files:**
- Modify: `frontend/src/FinancePage.tsx`
- Create: `frontend/src/FinancePage.css`

**Interfaces:**
- Consumes: `GET /api/analytics/channels?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`.
- Produces: быстрые периоды `week | month | quarter | year` и адаптивный список каналов.

- [ ] **Step 1: Добавить типы и функцию периода**

```tsx
type PeriodKey = 'week' | 'month' | 'quarter' | 'year'
type ChannelMetric = {
  channel: string
  total_amount: string
  count: number
  avg_check: string
  share_percent: string
}
type ChannelAnalytics = { period_total: string; channels: ChannelMetric[] }

const periodRange = (period: PeriodKey) => {
  const end = dayjs()
  if (period === 'week') return [end.subtract(6, 'day'), end] as const
  if (period === 'quarter') return [end.subtract(2, 'month').startOf('month'), end] as const
  if (period === 'year') return [end.startOf('year'), end] as const
  return [end.startOf('month'), end] as const
}
```

- [ ] **Step 2: Загружать аналитику при смене периода**

```tsx
useEffect(() => {
  const [start, end] = periodRange(period)
  fetch(`${API}/api/analytics/channels?start_date=${start.format('YYYY-MM-DD')}&end_date=${end.format('YYYY-MM-DD')}`)
    .then((response) => {
      if (!response.ok) throw new Error('Не удалось загрузить аналитику каналов')
      return response.json()
    })
    .then(setChannelAnalytics)
    .catch(() => setError('Не удалось загрузить аналитику каналов'))
}, [period])
```

- [ ] **Step 3: Добавить блок с кнопками и метриками**

Использовать `Segmented` с подписями `Неделя`, `Месяц`, `3 месяца`, `Год`; для каждой строки отрисовать `Progress percent={Number(item.share_percent)}` и текст:

```tsx
<strong>{money(item.total_amount)} ₽</strong>
<span>{item.count} заявок</span>
<span>Средний чек {money(item.avg_check)} ₽</span>
```

При `channels.length === 0` показать `Empty` с текстом `Доходов за выбранный период нет`.

- [ ] **Step 4: Добавить адаптивные стили**

```css
.channel-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.channel-item { min-width: 0; }
.channel-metrics { display: flex; flex-wrap: wrap; gap: 8px 16px; }
@media (max-width: 767px) {
  .channel-list { grid-template-columns: 1fr; }
  .channel-periods { width: 100%; overflow-x: auto; }
}
```

- [ ] **Step 5: Запустить frontend lint и build**

Run: `npm run lint`

Run: `npm run build`

Workdir: `frontend`

Expected: обе команды завершаются exit code 0.

---

### Task 5: Миграция, живой API-сценарий и браузерная проверка

**Files:**
- Modify only if defects are found: files listed in Tasks 1–4.
- Create outside Git: temporary screenshots in `C:\Users\user\Desktop\ЭкоДез\_runtime_docs\`.

**Interfaces:**
- Consumes: finished backend/frontend and local database.
- Produces: evidence for acceptance report.

- [ ] **Step 1: Выполнить миграцию**

Run: `backend\.venv\Scripts\python.exe -m alembic upgrade head`

Workdir: `backend`

Expected: database revision becomes `c4e8a1b7d903` and `transactions.channel` exists.

- [ ] **Step 2: Освободить только порты проекта и перезапустить сервисы**

Определить PID слушателей 8000 и 5173, остановить только подтверждённые процессы проекта, затем запустить:

```powershell
backend\.venv\Scripts\uvicorn.exe app.main:app --port 8000
npm run dev -- --host 0.0.0.0
```

Expected: `GET http://127.0.0.1:8000/health` содержит `status=ok`; `http://localhost:5173` возвращает HTTP 200; backend-log содержит `TG poller: started`.

- [ ] **Step 3: Выполнить синтетический API-сценарий**

Через `POST /api/day/entry` создать текущим месяцем:

```json
{"kind":"income","category":"Другие работы","amount":"5000.00","channel":"Авито","comment":"TEST CHANNEL 1","entered_by":"Артем"}
{"kind":"income","category":"Другие работы","amount":"7000.00","channel":"Авито","comment":"TEST CHANNEL 2","entered_by":"Артем"}
{"kind":"income","category":"Другие работы","amount":"10000.00","channel":"Сарафан","comment":"TEST CHANNEL 3","entered_by":"Артем"}
{"kind":"income","category":"Другие работы","amount":"3000.00","channel":null,"comment":"TEST CHANNEL 4","entered_by":"Артем"}
```

Вызвать API за текущий месяц и проверить для Авито `count=2`, `total_amount=12000.00`, `avg_check=6000.00`; проверить группу `Не указан` и суммы долей. После доказательства удалить только созданные manual-записи через разрешённый DELETE в тот же день.

- [ ] **Step 4: Проверить UI и сделать скриншоты**

Открыть экран `Финансы`, выбрать `Месяц`, убедиться, что progress-bars и цифры совпадают с API. Сохранить desktop screenshot и mobile screenshot при ширине меньше 768 px в `C:\Users\user\Desktop\ЭкоДез\_runtime_docs\`.

- [ ] **Step 5: Повторить полные проверки после очистки сценария**

Run: `backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v`

Run: `npm run lint`

Run: `npm run build`

Expected: все команды exit code 0.

---

### Task 6: Безопасный продуктовый коммит и push

**Files:**
- Stage only: `backend/app/channels.py`
- Stage only: `backend/app/models.py`
- Stage only: `backend/app/main.py`
- Stage only: `backend/alembic/versions/c4e8a1b7d903_transaction_channel.py`
- Stage only: `backend/tests/test_channel_analytics_api.py`
- Stage only: `backend/tests/test_day_api.py`
- Stage only: `frontend/src/DayPage.tsx`
- Stage only: `frontend/src/DayPage.css`
- Stage only: `frontend/src/FinancePage.tsx`
- Stage only: `frontend/src/FinancePage.css`

**Interfaces:**
- Consumes: all green gates and verified screenshots.
- Produces: commit `Core: channel analytics v1` on `main` and push to `origin/main`.

- [ ] **Step 1: Проверить рабочее дерево и секреты**

Run: `git status --short`

Run: `git diff --check -- <all target files>`

Run: `git check-ignore -v backend/.env backend/tg_offset.json backend/attachments`

Expected: unrelated `frontend/` deletion entries and `backend/sample_order.txt` are not staged; secret paths remain ignored.

- [ ] **Step 2: Индексировать только целевые файлы**

Run: `git add -- backend/app/channels.py backend/app/models.py backend/app/main.py backend/alembic/versions/c4e8a1b7d903_transaction_channel.py backend/tests/test_channel_analytics_api.py backend/tests/test_day_api.py frontend/src/DayPage.tsx frontend/src/DayPage.css frontend/src/FinancePage.tsx frontend/src/FinancePage.css`

- [ ] **Step 3: Проверить staged diff**

Run: `git diff --cached --name-status`

Expected: только десять файлов из Step 2; `.env`, вложений, offset и `sample_order.txt` нет.

- [ ] **Step 4: Создать коммит и отправить**

Run: `git commit -m "Core: channel analytics v1"`

Run: `git push origin main`

Expected: push в `https://github.com/ollalaaaaaa-pixel/ekodez-core.git` завершается успешно.
