# Ads Analytics Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить локальный owner-only контур рекламной аналитики с безопасным импортом, атрибуцией, метриками, уведомлениями и еженедельным агентом.

**Architecture:** Функциональность разделяется на модели/миграцию, чистые парсеры, сервисы импорта и атрибуции, метрики/агент, FastAPI router и React-экран. Существующий scheduler вызывает рекламные задания, а HMAC телефонов использует доменно-разделённый ключ из PII-конфигурации.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, openpyxl, stdlib csv/html, React, TypeScript, Ant Design, unittest, Vitest.

**Spec:** `docs/ads/ads-agent-design.md`

## Global Constraints

- Рабочая БД не мигрируется; миграционные тесты используют временную SQLite.
- Полные телефоны не сохраняются в `ad_call_log`, логах, API, UI, Telegram или уведомлениях.
- Каждый `/api/ads/*` endpoint вызывает `require_owner`.
- `C:\D\Экодез\ads\config.json` остаётся вне Git; в Git только `docs/ads-config.example.json`.
- Автоматическая атрибуция не перезаписывает `manual`.
- Агент не содержит функции отправки email.
- Деньги вычисляются через `Decimal` и сериализуются строкой с двумя знаками.

---

### Task 1: Схема, миграция и HMAC телефона

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/security/ad_phone_hash.py`
- Create: `backend/alembic/versions/a1d5e7c9f302_ads_analytics.py`
- Create: `backend/tests/test_ads_migration.py`
- Create: `backend/tests/test_ad_phone_hash.py`

**Interfaces:**
- Produces: `phone_hmac(phone: str, key: str | None = None) -> str`.
- Produces SQLAlchemy models `AdSpend`, `AdCallLog`, `AdImportRun`, `Notification`.

- [ ] Написать тест миграции: поднять предыдущую head на временной SQLite, вставить лид, выполнить upgrade и проверить новые таблицы/колонки, сохранение строки, `PRAGMA integrity_check = ok` и одну head.
- [ ] Запустить тест и подтвердить ожидаемый FAIL из-за отсутствующей ревизии.
- [ ] Написать тест HMAC: одинаковый номер в форматах `+7`/`8` даёт один хеш при одном ключе, другой ключ даёт другой хеш, номер не является подстрокой результата или сериализованной модели.
- [ ] Запустить тест и подтвердить FAIL из-за отсутствующего `phone_hmac`.
- [ ] Добавить модели, ограничения, индексы и SQLite batch migration.
- [ ] Реализовать HMAC-SHA256 через `hmac.new(derived_key, canonical_digits, hashlib.sha256)`; derived key получить через HMAC с меткой `ekodez-ad-phone-v1` от `PII_FERNET_KEY`.
- [ ] Запустить оба теста до PASS.

### Task 2: Конфигурация и парсеры файлов

**Files:**
- Create: `docs/ads-config.example.json`
- Create: `backend/app/ads/config.py`
- Create: `backend/app/ads/parsers.py`
- Create: `backend/tests/test_ads_config.py`
- Create: `backend/tests/test_ads_parsers.py`

**Interfaces:**
- Produces: `load_ads_config(path: Path = Path(r"C:\D\Экодез\ads\config.json")) -> AdsConfig`.
- Produces: `parse_ads_file(path: Path, platform: str) -> ParsedAdsFile` containing `spend_rows` and `call_rows`.

- [ ] Написать failing tests для default reminder 7, nullable monetary thresholds и отказа от неизвестной площадки.
- [ ] Написать failing parser fixtures для CSV, XLSX и HTML/XLS с вариантами русских заголовков, Decimal-суммами, пустым файлом и неизвестными колонками.
- [ ] Реализовать dataclass-конфигурацию и проверку разрешённого корня каталогов.
- [ ] Реализовать нормализацию заголовков и адаптеры форматов без pandas.
- [ ] Проверить, что parser возвращает только HMAC звонка и не возвращает исходный телефон.
- [ ] Запустить parser/config tests до PASS.

### Task 3: Идемпотентный импорт, журнал и уведомления

**Files:**
- Create: `backend/app/ads/importer.py`
- Create: `backend/app/ads/notifications.py`
- Create: `backend/tests/test_ads_importer.py`
- Create: `backend/tests/test_ads_notifications.py`

**Interfaces:**
- Produces: `import_ads_file(session: Session, platform: str, path: Path, pii_key: str | None = None) -> ImportSummary`.
- Produces: `create_notification(session, kind: str, payload: dict[str, object], now: datetime) -> Notification`.

- [ ] Написать failing test повторного импорта одного периода: одна строка `ad_spend`, обновлённые значения и два безопасных журнала запуска.
- [ ] Написать failing tests `ads_import_ok/error`, отката рекламных строк при ошибке и отсутствия номера в БД/уведомлении.
- [ ] Реализовать upsert через SQLAlchemy select/update внутри переданной транзакции.
- [ ] Реализовать allowlist payload для пяти ad-видов уведомлений.
- [ ] Запустить tests до PASS.

### Task 4: UTM, phone_match и manual

**Files:**
- Create: `backend/app/ads/attribution.py`
- Create: `backend/tests/test_ads_attribution.py`

**Interfaces:**
- Produces: `attribute_lead(session: Session, lead: Lead, now: datetime) -> AttributionResult`.
- Produces: `set_manual_attribution(session: Session, lead: Lead, platform: str | None, now: datetime) -> None`.

- [ ] Написать failing test UTM alias → platform/method `utm`.
- [ ] Написать failing test единственного HMAC-совпадения ±7 дней → `phone_match`.
- [ ] Написать failing tests разных ключей, нескольких площадок, отсутствующего PII-ключа и отсутствия plaintext.
- [ ] Написать failing test неизменности `manual` после повторной автоматики.
- [ ] Реализовать приоритеты и очередь неатрибутированных/спорных лидов.
- [ ] Запустить tests до PASS.

### Task 5: Метрики, алерты, напоминания и черновики

**Files:**
- Create: `backend/app/ads/metrics.py`
- Create: `backend/app/ads/agent.py`
- Create: `backend/tests/test_ads_metrics.py`
- Create: `backend/tests/test_ads_agent.py`

**Interfaces:**
- Produces: `ads_metrics(session: Session, start: date, end: date) -> AdsMetricsResult`.
- Produces: `run_ads_weekly(engine: Engine, now: datetime, sender: Callable[[str], bool]) -> WeeklyResult`.
- Produces: `create_upload_reminders(session: Session, config: AdsConfig, now: datetime) -> list[Notification]`.

- [ ] Написать Decimal-фикстуры CPL и ROMI по площадке/кампании, включая нулевой расход и ноль лидов.
- [ ] Написать failing test напоминания один раз за период и отсутствия напоминания после свежего `ok`.
- [ ] Написать failing tests алерта после двух недель высокого CPL и расхода выше порога при нуле лидов.
- [ ] Написать failing test безопасного TG-текста и создания Markdown-черновика без отправки email.
- [ ] Реализовать метрики, дедупликацию уведомлений и версионированный путь черновика в `C:\D\Экодез\analysis\`.
- [ ] Запустить tests до PASS.

### Task 6: Owner-only FastAPI router

**Files:**
- Create: `backend/app/ads/api.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_ads_api.py`

**Interfaces:**
- Produces endpoints `/api/ads/import`, `/metrics`, `/import-runs`, `/attribution-queue`, `/leads/{id}/attribution`, `/notifications`, `/notifications/unread-count`, `/notifications/{id}/read`.

- [ ] Написать failing API tests: anonymous 401, master 403, owner 200 для каждого endpoint.
- [ ] Написать failing tests сериализации денег и полного отсутствия поля телефона.
- [ ] Реализовать router factory с `require_owner(request)` в каждой операции.
- [ ] Подключить router в `main.py` без изменения существующих маршрутов.
- [ ] Запустить API tests до PASS.

### Task 7: Scheduler

**Files:**
- Modify: `backend/app/reports/scheduler.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_ads_scheduler.py`

**Interfaces:**
- Produces: `run_due_ads_jobs(engine: Engine, now: datetime) -> tuple[str, ...]`.

- [ ] Написать failing tests времени понедельника 09:15/09:20/09:30 и идемпотентности одного запуска.
- [ ] Реализовать вызовы importer/reminder/weekly agent в существующем scheduler loop.
- [ ] Проверить, что scheduler не запускается при отсутствующей конфигурации и сообщает degraded без секретов.
- [ ] Запустить scheduler tests до PASS.

### Task 8: Owner-only React UI и колокольчик

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/auth.ts`
- Create: `frontend/src/AdsPage.tsx`
- Create: `frontend/src/AdsPage.css`
- Create: `frontend/src/AdsPage.test.tsx`
- Create: `frontend/src/App.ads.test.tsx`

**Interfaces:**
- Consumes owner session role and `/api/ads/*` responses.
- Produces owner-only menu item, page, attribution controls, import log and notification bell.

- [ ] Написать failing test: master не видит «Реклама» и колокольчик, owner видит оба.
- [ ] Написать failing tests счётчика, отметки прочитанным, кнопки импорта, журнала и manual-атрибуции.
- [ ] Реализовать сохранение session role, owner-only menu and bell.
- [ ] Реализовать агрегированные таблицы без телефонного поля.
- [ ] Запустить Vitest до PASS.

### Task 9: Финальная проверка и поставка ветки

**Files:**
- Modify: `docs/ads/ads-agent-implementation-plan.md` только для отметок выполненных шагов.

- [ ] На временной SQLite выполнить upgrade до head, `PRAGMA integrity_check`, сверку строк и `alembic heads` = 1.
- [ ] Выполнить backend unittest, ruff, black --check и mypy.
- [ ] Выполнить frontend vitest, lint и build.
- [ ] Проверить diff на `.env`, БД, XLS/XLSX, ключи, телефоны и рабочий `config.json`.
- [ ] Закоммитить итог сообщением `feat: ads analytics agent with attribution`.
- [ ] Push `feat/ads-agent` и подтвердить remote SHA.
- [ ] Не merge в main, не мигрировать рабочую БД и не перезапускать сервисы.
