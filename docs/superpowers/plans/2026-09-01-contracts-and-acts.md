# Contracts and Acts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить договоры, акты обследования, месячные пакеты DOCX и контроль явной оплаты в карточку объекта.

**Architecture:** Расширить существующий `Contract`, добавить отдельные `InspectionReport` и `ContractPeriod`, а бизнес-логику календаря и DOCX вынести из HTTP-слоя. UI остаётся внутри карточки объекта; документы создаются только во внешней папке и доступны только с localhost.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic/SQLite, Pydantic 2, python-docx, React 19, Ant Design 6, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-01-contracts-and-acts-design.md`

## Global Constraints

- Цена вводится владельцем вручную и не имеет системного значения по умолчанию.
- Деньги хранятся как Decimal/Numeric и сериализуются строкой с двумя знаками.
- Полные реквизиты не выводятся в логи и обычные API-ответы.
- Раскрытие реквизитов и DOCX доступны только с `127.0.0.1`/`::1` по `request.client.host`.
- Рабочие дни используют только статический календарь РФ 2025–2027.
- Генерируемые документы находятся вне Git в `C:\D\Экодез\hostels-docs`.
- Посторонние untracked-файлы не добавляются в коммит.

---

### Task 1: Модели и SQLite-миграция

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/a7c9e2d4f601_contracts_and_acts.py`
- Create: `backend/tests/test_contracts_migration.py`

**Interfaces:**
- Produces: `Contract`, `InspectionReport`, `ContractPeriod` и расширенный `Client`.

- [ ] Написать миграционный тест: upgrade свежей SQLite-БД, сохранение старой цены, nullable периодичность старого договора, новые ограничения и downgrade.
- [ ] Запустить тест и подтвердить падение из-за отсутствующей ревизии/полей.
- [ ] Добавить модели и SQLite batch-миграцию без серверных выражений, несовместимых с SQLite.
- [ ] Повторить тест до зелёного результата.

### Task 2: Календарь РФ и правила периода

**Files:**
- Create: `backend/app/business_calendar.py`
- Create: `backend/app/contracts.py`
- Create: `backend/tests/test_contracts.py`

**Interfaces:**
- Produces: `add_business_days(day: date, count: int) -> date`, `is_paid_month(contract, month) -> bool`, `next_invoice_number(session) -> str`, создание периода с наследованием `preparations`.

- [ ] Написать тесты 2026 года: новогодние выходные, обычные выходные, переносы, выход за диапазон, monthly/semiannual/custom, следующий номер счёта, наследование препаратов и дефолты.
- [ ] Запустить тесты и подтвердить ожидаемые падения.
- [ ] Реализовать минимальные чистые функции и сервис периода.
- [ ] Запустить тесты до зелёного результата и отрефакторить без изменения поведения.

### Task 3: API договоров, обследований и оплаты

**Files:**
- Modify: `backend/app/objects.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_contracts_api.py`

**Interfaces:**
- Produces: API обновления реквизитов/договора, upsert обследования и периода, подписание, явную привязку доходного `transaction_id`, таймлайн.

- [ ] Написать API-тесты ручной цены, валидации месяцев, маскирования реквизитов, запрета раскрытия извне, дефолтов обследования, редактируемого номера счёта и явной оплаты.
- [ ] Запустить тесты и подтвердить 404/422 из-за отсутствующих маршрутов.
- [ ] Реализовать схемы, сериализацию и маршруты; не логировать payload реквизитов.
- [ ] Запустить тесты до зелёного результата.

### Task 4: Генератор DOCX и версионирование

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`
- Create: `backend/app/document_packages.py`
- Create: `backend/tests/test_document_packages.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: `build_month_package(...) -> PackageManifest` и localhost-only POST/GET для генерации/скачивания.

- [ ] Добавить падающие тесты состава бесплатного/оплачиваемого месяца, полного заполнения токенов, запрета выхода из корневой папки, `v1/v2`, SHA-256 и отсутствия частичной версии при ошибке.
- [ ] Запустить тесты и подтвердить ожидаемые падения.
- [ ] Закрепить `python-docx`, реализовать замену токенов во всех абзацах/таблицах/колонтитулах и атомарную запись внешнего пакета.
- [ ] Запустить тесты до зелёного результата.
- [ ] Сформировать синтетические DOCX, отрендерить все страницы и визуально проверить их.

### Task 5: Telegram-напоминания

**Files:**
- Modify: `backend/app/reports/daily.py`
- Modify: `backend/tests/test_daily_reports.py`

**Interfaces:**
- Extends: `ReportSnapshot` и `format_daily_report()` списками пакетов к выдаче и просроченных оплат.

- [ ] Написать тесты: напоминание только 25-го, отсутствие реквизитов, просрочка после 5 рабочих дней, отсутствие просрочки при связанном доходе.
- [ ] Запустить тесты и подтвердить ожидаемые падения.
- [ ] Реализовать запросы и безопасное форматирование.
- [ ] Запустить тесты до зелёного результата.

### Task 6: UI карточки объекта

**Files:**
- Modify: `frontend/src/ObjectsPage.tsx`
- Modify: `frontend/src/ObjectsPage.test.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Produces: формы плательщика, договора, обследования и периода; генерацию пакета; таймлайн и явную привязку оплаты.

- [ ] Написать Vitest-сценарии: цена не предзаполнена, semiannual требует месяцы, показатели редактируются, номер счёта можно изменить, пакет показывает правильный состав, оплата выбирается вручную.
- [ ] Запустить тест и подтвердить ожидаемое падение по отсутствующим элементам.
- [ ] Реализовать UI минимально в существующем Drawer и адаптировать его для мобильной ширины.
- [ ] Запустить тесты до зелёного результата.

### Task 7: Рабочая миграция, приёмка и gate

**Files:**
- Create outside Git: `C:\D\Экодез\backups\ekodez-pre-contracts-acts-<timestamp>.db`
- Create outside Git: `C:\D\Экодез\hostels-docs\2026-09\...`

**Interfaces:**
- Consumes: весь реализованный API/UI и шаблоны.

- [ ] Определить фактический SQLite-файл без вывода секретов и сделать проверенную резервную копию вне Git.
- [ ] Применить `alembic upgrade head`, проверить `/health` и `/health/db`.
- [ ] Выполнить backend unittest, ruff, black --check, mypy; frontend test, lint, build.
- [ ] Через UI вручную создать договоры «Спутник» и «Фреш», вводя предоставленные владельцем цены и месяцы; если данных нет, остановить только эту часть как HANDOFF, не выдумывать их.
- [ ] Сформировать сентябрьские пакеты, открыть и визуально проверить каждый DOCX.
- [ ] Удалить только синтетические тестовые записи; реальные данные не изменять вне явно утверждённых двух договоров.
- [ ] Проверить staged-файлы на `.env`, БД, документы, вложения и полные ИНН.
- [ ] Закоммитить только файлы этапа сообщением `feat: contracts and acts`, push в `main`, сверить local и remote SHA.
