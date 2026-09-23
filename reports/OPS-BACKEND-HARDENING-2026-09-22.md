# OPS-BACKEND-HARDENING — 22.09.2026

## Статус

Подготовлено в `feat/ops-backend-hardening`, отдельный worktree
`C:\D\Экодез\ekodez-core-ops-hardening`. Gate зелёный. WAITING FOR OWNER:
боевой watchdog не установлен, merge/main, рестарты и рабочая БД не затронуты.
Коммит и push ветки выполняются отдельной командой владельца от 23.09.2026;
точный SHA подтверждается после публикации ветки в итоговом ответе.

## Факты: реализация

1. `backend/scripts/backend_watchdog.py`: два localhost health endpoint, timeout 5 с;
   первый провал — warning, второй — одна попытка рестарта. Счётчик и cooldown
   сохраняются атомарно на диске; Windows lock исключает параллельное вмешательство.
   Cooldown 10 минут действует и после неудачной попытки. Флаг deploy-in-progress
   подавляет действия и сбрасывает серию провалов. Запуск из feature-worktree запрещён.
2. `deployment/autostart/restart-backend.ps1`: проверка пути Python, команды,
   instance-root, владельца и времени создания PID; отказ при чужом процессе/порте.
   Остановка задачи → проверенный PID → свободный порт → старт задачи → новый
   WRAPPER START → оба health. Неопределённость чтения порта не считается свободным портом.
3. Уведомление после подтверждённого восстановления — ровно
   `backend перезапущен watchdog: health fail x2`. Токен и chat_id берутся из существующего
   окружения; сообщения исключений и URL Telegram не пишутся в лог.
   Реальных TG-сообщений при разработке не отправляли.
4. `install-watchdog.ps1`: подготовлена отдельная EkodezBackendWatchdog каждые 5 минут,
   IgnoreNew; установка требует явного -Apply. Установщик не запускался.
5. `backend/scripts/run_backend.py`: явная фабрика SelectorEventLoop, concurrency 200,
   keep-alive 5 с, graceful shutdown 20 с; ISO 8601 timestamp с миллисекундами и часовым
   поясом в access/default логировании Uvicorn. Proxy headers остаются отключены.
6. Подготовлены launcher и wrapper: START содержит предыдущий exit code либо unknown
   и последнюю доступную строку процесса (хвост 50 строк); чувствительные шаблоны
   маскируются. Код предыдущего аварийного запуска не подменяется старым EXIT.
   Существующие файлы `C:\D\Экодез\scripts` не заменялись.

## Разбор WinError 64 и смягчение

Проверены установленный Python 3.12.14 и Uvicorn 0.52.1. В установленном Uvicorn
однопроцессный Windows-запуск выбирает Proactor. В Python `proactor_events.py`
путь ошибки accept может закрыть слушающий сокет при продолжающем жить процессе.
Это объясняет механизм ранее наблюдавшегося сочетания «процесс жив, listener исчез»;
первичный сетевой источник WinError 64 не доказан и остаётся UNRESOLVED.

Применено программное смягчение в коде ветки: явная фабрика SelectorEventLoop
обходит этот Proactor accept-путь. Проверены тип фактически возвращаемого Uvicorn
цикла и обмен по двум подключениям на изолированном временном сокете.
Это не утверждение, что реальный WinError 64 воспроизведён или навсегда устранён.

Отказанные варианты:

- Обновление Python/Uvicorn без найденного подтверждённого исправления именно этого
  отказа: не выполнялось; зависимости боевого venv не изменялись.
- Только глобальная Windows loop policy: недостаточно, Uvicorn использует свою фабрику.
- Только keep-alive/graceful: не восстанавливает уже закрытый listener. Эти ограничения
  добавлены как дополнительные меры, не представлены лечением причины.

Официальные источники:

- [Python: Windows asyncio limitations](https://docs.python.org/3.12/library/asyncio-platforms.html)
- [Uvicorn: event loop](https://uvicorn.dev/concepts/event-loop/)

## Проверки

Все OS-мутации и HTTP-вызовы в тесте PowerShell заменены функциями-моками;
wrapper проверен на временной папке с подменённым Start-Process.

- Backend unittest: **260 tests, OK** (полный discover).
- Ruff: **All checks passed**.
- Black: **102 files would be left unchanged**.
- Mypy: **Success, 76 source files** (`app tests` и оба изменённых Python launcher/watchdog).
- После правки только длины строк теста повторно: 6 PowerShell-тестов OK и все три
  статические проверки зелёные.
- `git diff --check`: ошибок нет.

Ключевые тесты:

- test_two_failures_restart_once_and_send_only_safe_payload
- test_deployment_flag_resets_sequence_and_disables_actions
- test_flag_appearing_during_probe_blocks_restart
- test_success_breaks_consecutive_failure_sequence
- test_failed_restart_no_success_alert_and_cooldown_persisted
- test_state_survives_process_boundaries
- test_both_health_endpoints_are_checked_after_exception
- test_access_timestamp_is_iso8601_with_timezone_and_greppable
- test_uvicorn_uses_explicit_selector_factory
- test_selector_serves_requests_on_isolated_socket
- test_verified_process_restart_order_and_both_probes
- test_foreign_port_owner_prevents_all_mutations
- test_pid_reuse_prevents_kill_and_start
- test_other_process_owner_prevents_all_mutations
- test_real_deploy_flag_prevents_all_mutations
- test_wrapper_records_previous_exit_and_process_last_line

Миграционные регрессии полного gate использовали тестовые БД; штатный старый helper
создал резервные копии этих синтетических БД в общем backups. Рабочая БД не открывалась
для записи и не мигрировалась. Тестовые backup-файлы не удалялись.

## Границы и риски

- Production main остаётся `f7e558d9bdacba883b6f3fe2b53a6116fefdc7b6`, его worktree чист.
- Read-only netstat после работы: порт 8000 LISTENING, PID 21848.
  Последний WRAPPER START backend — 22.09.2026 21:19:43.760, то есть предыдущий
  разрешённый recovery, не новый рестарт этой задачи.
- Прямое чтение задач/CIM из sandbox получило «Отказано в доступе»; статус задач
  не объявляется проверенным. На деплое требуется проверить полномочия учётной записи
  для CIM и stop/start. Скрипт при отказе прав прекращает вмешательство.
- Selector ограничен 512 сокетами, не поддерживает asyncio subprocess/pipes.
  HTTP concurrency 200 не является абсолютным лимитом всех сокетов процесса;
  после одобрения нужна нагрузочная/интеграционная проверка.
- Подготовленная задача Interactive: работает при активном входе пользователя;
  непрерывная служба без входа потребует отдельного согласованного варианта запуска.
- Флаг deploy-in-progress до нового вмешательства подавляет watchdog. Уже начатый
  рестарт удерживает общий лок и доводит процедуру до запуска задачи и health-проверки.
- Автоматическая доставка Telegram и настоящая регистрация/перезагрузка сервисов
  на боевом окружении не проверены намеренно до команды владельца.

## Применённые навыки

- systematic-debugging — проверка механизма закрытия listener и версий до выбора меры.
- service-restart-runbook — порядок действий и проверка свежего wrapper/health.
- owner-approval-gate — отдельная ветка, без production-установки, merge и отправок.
- verification-before-completion — синтетические тесты и полный backend gate.
- receiving-code-review — воспроизведение P1 до исправления.
- test-driven-development — красный/зелёный тест появления флага после остановки,
  параллельного вызова и восстановления stale-лока.

## HANDOFF TO владельцу / Qwen

Код готов к ревью, не к объявлению боевого инцидента окончательно устранённым.
План применения и отката: `C:\D\Экодез\ekodez-core-ops-hardening\deployment\autostart\README.md`.
Следующий этап после «применяй»: согласованный merge, копии активных скриптов,
контролируемый первый backend-рестарт с новым launcher, health x2, затем включение
watchdog. Миграция БД и рестарт frontend не требуются.

## Дополнение 23.09.2026 — исправление P1 и стык с Gnom

Ветка перепривязана на `feat/gnom-import` (голова перед ребейзом `de33bf5`),
которая уже содержит ADS. В `run-autostart-hidden.ps1` сохранены и безопасный
reboot-context из Gnom, и предыдущие exit code / строка процесса из hardening.
`backend/app/reports/scheduler.py` этой веткой не менялся: Gnom 09:10 и ADS
09:15/09:20/09:30 остаются в общей цепочке.

Общий `logs/backend-restart.lock` создаётся атомарно. Свежий лок подавляет цикл
watchdog и параллельный рестарт; старый (по умолчанию 10 минут) при двух провалах
health помечается stale и заменяется. Флаг, появившийся после остановки задачи,
пишет warning, но не прерывает запуск и проверку health. Лок освобождается после
health-проверки; если до неё не дошли, он остаётся до восстановления по таймауту.
Новые синтетические проверки: `test_flag_after_stop_still_starts_backend_and_checks_health`,
`test_parallel_restart_has_one_owner_and_second_is_lock_busy`,
`test_stale_lock_after_two_health_failures_restarts_once` и
`test_stale_restart_lock_is_removed_before_starting`.

Контролируемый деплой при установленном флаге использует `-Deployment` и тот же
эксклюзивный лок. Без этого параметра флаг проверяется один раз до остановки
задачи и подавляет новый рестарт. Синтетический тест
`test_explicit_deployment_uses_same_restart_lock` подтверждает общий путь.

После ребейза закреплённый в требованиях mypy 1.18.2 выявил 30 ошибок типизации
в унаследованных тестах ADS/Gnom. Исправлены только аннотации и утверждения о
наличии ожидаемых тестовых сущностей; рабочая логика ADS/Gnom не менялась.
Финальная повторная проверка: 330 backend-тестов прошли, ruff, black и mypy
1.18.2 — без ошибок; синтетический тест reboot-context — PASS. В полном
тестовом выводе остаётся шум от унаследованных
фоновых тестовых потоков (неуспешная TG-попытка и отсутствие `scheduler_state`
в отдельном потоке с in-memory SQLite); итог unittest — `OK`. Боевые сервисы,
БД и main не запускались и не изменялись.

## Дополнение 23.09.2026 — P1: безопасные записи, P2: lifecycle воркеров

### Статус

Фиксы реализованы в `feat/ops-backend-hardening`; gate зелёный. Готово к повторному
ревью. Применение на production — **WAITING FOR OWNER**.
Разрешение владельца: «Gate: полный прогон backend-тестов без фонового шума в
выводе teardown, ruff/black/mypy; push; SHA». Это разрешение на feature-коммит и
push, не на merge/main, миграцию БД или перезапуск сервисов.

### Факты: P1

- `Write-LogSafe` перехватывает ошибку записи и пробует безопасный stderr;
  ошибка stderr также подавляется. Предупреждение о флаге между stop и start
  больше не может прервать восстановление.
- Чтение wrapper-лога защищено `Get-WrapperStartSafe`. Если лог недоступен,
  процедура всё равно запускает задачу и проверяет оба health. Этот режим
  сопровождается предупреждением и **не считается наблюдением WRAPPER START**.
  При доступном логе сохраняется требование новой строки старта.
- Закрытие файлового дескриптора и удаление лока защищены; ошибка очистки
  не подменяет успешный результат health. Сохранившийся лок восстанавливается
  позднее по stale-таймауту. State-файлы внутри процедуры не записываются.
- Проверки личности PID и захват лока остаются обязательными до stop.
  Критичные OS-действия после stop обёрнуты в try/finally с обязательным start;
  ошибка kill/освобождения порта не обходит start и последующие health-зонды.
- Синтетика недоступного лога сначала воспроизвела exit 1; после фикса — exit 0,
  ровно stop → kill → start → `/health` → `/health/db`, warning в stderr.
- Watchdog не получил прямых обращений к БД/frontend, его payload не изменён.

### Факты: P2 — затронут унаследованный код

**P2 меняет унаследованные `backend/app/main.py` и тесты TG-auth**, а также
жизненный цикл TG-поллера и планировщика. Это не только изменение watchdog.

- FastAPI lifespan владеет общим `WorkerRegistry`: TG-поллер, планировщик,
  retention-worker и будущие зарегистрированные воркеры получают stop до
  первого join. Общий бюджет ожидания — 20 секунд; незавершившийся поток
  приводит к явной ошибке shutdown.
- Ожидания между итерациями TG/планировщика заменены на `Event.wait`, чтобы
  stop прерывал паузу. Статусы отражают живой поток, а не устаревший флаг.
  Действующие расписания Gnom/ADS не изменялись.
- Anti-replay использует подмены запуска TG/планировщика и сетевого транспорта;
  TestClient выходит из lifespan до уничтожения тестовой БД. Проверяются
  отсутствие новых потоков и отсутствие обращений к сети.
- Интеграционная синтетика запускает настоящие циклы воркеров с подменённой
  сетью и временной БД, регистрирует дополнительный воркер, затем проверяет
  отсутствие потоков и сетевых вызовов после выхода из lifespan.
- Первый полный прогон обнаружил три старых теста `test_tg_agent.py`, в которых
  остановка цикла зависела от подмены `sleep`. Тестовый процесс остановлен по
  проверенным PID/командной строке; подмена перенесена на `Event.wait`.
  Следующий полный прогон завершился штатно. Боевые процессы не останавливались.

### Свежий gate

- Полный backend discover: **334 tests, OK**, 27.831 с.
- Дополнительный контроль полного прогона: `background_errors=0`,
  `workers_after=[]`, `teardown_noise=False` (нет `OperationalError` и
  `Exception in thread`). Диагностические сообщения намеренно провоцируемых
  ошибок отдельных тестов не являются фоновым шумом teardown.
- Пять последовательных прогонов **в одном Python-процессе**: по **42 tests, OK**;
  модули `test_worker_lifecycle`, `test_tg_auth_api`, `test_tg_poller_logging`,
  `test_tg_agent`, `test_pii_retention`. На каждом прогоне: 0 фоновых исключений,
  0 оставшихся потоков, 0 teardown-шумов. Внешняя сеть подменена.
- Ruff: **All checks passed**; Black: **106 files unchanged**;
  pure-Python mypy **1.18.2: Success, 104 source files**.
- Frontend `pnpm lint` и `pnpm build`: exit 0. Сохранились 8 предупреждений
  о setState в effect и предупреждение Vite о chunk >500 kB; frontend-код
  этой задачей не менялся. Зависимости установлены только в feature-worktree.
- Независимое read-only ревью P1/P2: блокирующих дефектов не найдено;
  ограничение незавершившегося I/O и таймаута shutdown подтверждено как
  явно задокументированное. Gate ревьюером повторно не запускался.
- Миграционные тесты полного gate и их бэкапы — только временные синтетические
  SQLite. Рабочая БД не использовалась тестами. Ранний целевой прогон создал
  три бэкапа синтетической `daily-reports` БД в общем backups; это не бэкапы
  рабочей БД, они не удалялись и не добавлялись в Git.

Ключевые регрессии:

- `test_unavailable_log_does_not_interrupt_restart_or_health`;
- `test_flag_after_stop_still_starts_backend_and_checks_health`;
- `test_parallel_restart_has_one_owner_and_second_is_lock_busy` (код 21);
- `test_stale_lock_after_two_health_failures_restarts_once`;
- `test_explicit_deployment_uses_same_restart_lock`;
- `test_shutdown_joins_all_workers_and_has_no_network_after_teardown`;
- `test_registry_signals_all_workers_before_joining`;
- `test_registry_reports_timeout_instead_of_claiming_clean_shutdown`;
- `test_original_challenge_cookie_cannot_be_replayed_after_success`.

### Границы и риски

- Main остаётся `f7e558d9bdacba883b6f3fe2b53a6116fefdc7b6`, его worktree чист.
  Единственная head feature-цепочки — `f3d7a0b2c458`.
- Рабочая БД прочитана через SQLite `mode=ro`: `f1b5d8c0e236`.
  Миграций или записей в неё в этой задаче не выполнялось.
- Вечерняя проверка 23.09: backend PID 4572 (запуск 19:10:12), frontend PID 12696
  (19:10:44); оба порта LISTENING. Последние WRAPPER START: backend
  19:10:12.106, frontend 19:10:42.413. Это отличается от утреннего снимка
  предыдущего дополнения; утверждать «не перезапускались с 22.09» нельзя.
  Эти запуски предшествуют вечернему gate; инициатор здесь не расследовался
  (**UNRESOLVED**). Агент не выполнял stop/start боевых задач.
- Python-потоки не убиваются принудительно: выполняющийся сетевой запрос или
  обработчик должен закончиться штатно. Если это занимает больше 20 секунд,
  shutdown сообщает об ошибке; гарантии прекращения зависшего чужого I/O нет.
- Недоступный лог не препятствует восстановлению, но уменьшает полноту
  диагностики: health подтверждён, логовое свидетельство старта недоступно.
- Настоящие рестарты, отправка Telegram и включение watchdog на production
  намеренно не проверялись до «применяй».

### Применённые навыки

- receiving-code-review — проверка замечаний и воспроизведение отказов;
- systematic-debugging — причины сбоя записи и утечек фоновых потоков;
- test-driven-development — красный/зелёный тест лога и lifecycle;
- verification-before-completion — полный свежий gate и пять повторов;
- requesting-code-review — независимая проверка диффа перед коммитом;
- service-restart-runbook — аудит последовательности stop/kill/start/health
  на синтетике, без запуска боевой процедуры;
- owner-approval-gate — только feature-ветка, тестовая среда и разрешённый push.

### HANDOFF TO владельцу / Qwen

Повторное read-only ревью этого P1/P2-фикса. Применение, merge в main,
миграция рабочей БД и перезапуск остаются запрещены без отдельного «применяй».
SHA коммита и совпадение remote фиксируются в итоговом сообщении после push.
