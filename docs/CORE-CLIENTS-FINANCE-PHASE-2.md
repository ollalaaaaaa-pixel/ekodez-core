# CORE-CLIENTS-FINANCE-PHASE-2

Утверждённая архитектура и граница реализации

1. Client становится самостоятельным плательщиком. Object.client_id nullable;
   Client.object_id удаляется SQLite batch. Перенос сверяет число клиентов,
   объектов и связей. Несколько клиентов одного объекта блокируют миграцию,
   автоматическое объединение запрещено. Перед применением файловая SQLite
   копируется средствами sqlite3.backup, проверяется integrity_check.
2. Витрина юридических лиц и ИП: поиск, фильтр типа, карточка с маскированными
   реквизитами, объектами, договорами, документами, операциями и осмотрами.
   Существующий localhost reveal сохраняется.
3. Единый справочник transaction_categories: title, kind income/expense,
   sort_order, is_active. Исходные названия сохраняются; удаление мягкое.
   Миграция переносит соответствия старых категорий в новые id.
4. Transaction.client_id nullable, бэкфилл по объекту. JSON tags для фильтрации.
5. mypy pure Python версии ниже 2; пин фиксируется после установки.

Порядок коммитов: feat: clients showcase; feat: finance-settings-drag-drop;
fix: mypy-pin-and-dist. Разработка только feat/clients-finance-phase-2.
Рабочая БД, merge main, сервисы и публикация ждут команды «применяй».

Проверки: миграции на синтетической SQLite с резервной копией; тесты API
списка и всех связей, PII, сохранности банковского маппинга, reorder и
soft-delete, тегов; unittest/ruff/black/mypy, vitest/lint/build, health на
изолированной БД; marketing-site build и отсутствие ekodez_bot в dist.
