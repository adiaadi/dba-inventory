# Replication Monitoring

Страница `/replication` и API `/replication/api` защищены существующей portal session.
Новый пункт **Replication** доступен в верхнем меню и sidebar Dashboard.
Портал только читает Zabbix: он не запускает cron, RMAN, SQL Agent jobs и не переключает роли.
Данные из скриншотов не загружаются как production-данные.

## Подключение

1. Настройте существующие `ZABBIX_URL`, `ZABBIX_API_TOKEN`, TLS/CA.
   API token должен иметь read-доступ к соответствующим hosts/items и истории.
2. `cp config/replication.example.json config/replication.json`.
3. Замените **все** примерные itemid, имена, расписания и пороги своими.
   Примерные ID не являются стандартными Zabbix keys. Найдите itemid в URL редактирования
   item в Zabbix либо через `item.get`. Для каждой базы/DR-replica создайте отдельную пару.
4. Проверьте конфигурацию внутри окружения приложения:

   ```bash
   python -c "from app.services.replication import read_config; print(len(read_config('config/replication.json').pairs), 'pairs')"
   ```

5. Для сборки из исходников:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.replication.yml up -d --build
   ```

   Для GHCR, **после сборки нового образа из этих изменений**:

   ```bash
   docker compose -f docker-compose.ghcr.yml -f docker-compose.replication.yml pull app
   docker compose -f docker-compose.ghcr.yml -f docker-compose.replication.yml up -d
   ```

   Добавьте ваши существующие domain/TLS/Zabbix CA override-файлы в ту же команду.
   Для локального запуска: `REPLICATION_CONFIG_FILE=config/replication.json` в `.env`.
   Не помещайте пароли БД или Zabbix token в JSON. Реальный JSON исключён из Git.

Без конфигурации страница показывает empty state. Пропущенные items, disabled hosts/items,
unsupported items, NULL/нечисловые/отрицательные значения и неизвестные состояния отображаются
как **NO DATA**, а не как нулевой lag. Неправильный JSON даёт понятную ошибку; детали в server logs.

## Контракт метрик

### Поиск по key: cbsetl

Готовая конфигурация: `config/replication.cbsetl.json`, primary `cbs-prod-db01`,
standby `cbs-dr-db`. Скопируйте её в `config/replication.json`, если конфигурации ещё нет;
в существующую конфигурацию добавьте пару из массива `pairs`.

Каждая метрика принимает либо `itemid`, либо `key`, например:
`"archive_gap": {"key": "db.replication.oracle.archive_gap"}`.
Для key обязательно поле пары `zabbix_host`: точное техническое имя хоста в Zabbix,
не отображаемое имя. В конфигурации cbsetl предполагается, что items размещены на
`cbs-dr-db`; если коллектор привязан к другому хосту, измените `zabbix_host`.
Поиск ограничен этим хостом и точным key. ID для истории определяется автоматически.
Отсутствующие/недоступные items дают NO DATA. Старые конфигурации с itemid поддерживаются.
Порог свежести cbsetl — 900 секунд; уточните его по реальному интервалу сбора.
Job items предполагаются текстовыми (`success`/`failed`); если Zabbix показывает эти
подписи через value mapping числовых кодов, задайте соответствующий `values` в JSON.

После обновления кода и подготовки JSON используйте команды Compose из раздела
«Подключение» выше. Для GHCR сначала требуется образ с поддержкой key.

Все metric keys перечислены в примере; для HEALTHY нужны все метрики выбранной СУБД.
Числовые значения: неотрицательные; время — **секунды**, WAL backlog — **байты**.
`factor: 60` переводит минуты в секунды (в примере SQL Server items предполагаются в минутах).
Если исходный item уже в секундах, удалите factor. `values` явно переводит коды в состояния;
не копируйте mapping кодов между разными коллекторами без проверки.

| СУБД | Источники и значения |
| --- | --- |
| Oracle | `archived_seq`, `copied_seq`, `applied_seq` — последовательности primary, подтверждённых файлов DR и применённых архивов standby; `archive_gap` — число архивов, ожидающих переноса; `pending_apply` — число скопированных, но не применённых; `last_success_age` — возраст последнего успешного apply; `transfer_job`, `apply_job` — `success`/`failed`. |
| PostgreSQL | `wal_backlog` — разница WAL LSN primary и replay LSN выбранной replica; `replay_lag` — задержка выбранной replica; `stream_state=streaming`; `sync_state=sync/async/quorum/potential`; `leader_lock=held/lost`; `replica_state=running/streaming`; `patroni_nodes` — число исправных узлов кластера. |
| SQL Server | `backup_age`, `copy_age`, `restore_age` — возраст соответствующей последней операции; `pending_files` — скопированные, но не восстановленные файлы для данной пары database/secondary; `backup_job`, `copy_job`, `restore_job` — `success`/`failed`. |

Oracle: не вычитайте MAX(sequence#) разных THREAD#/RESETLOGS-инкарнаций. Для RAC задавайте
пары по redo thread; archive_gap/pending_apply собираются отдельно с проверкой непрерывности
архивов. Успех cron означает успех переноса, а не применения; нужен отдельный результат RMAN.
Состояние после смены инкарнации должен нормализовать источник метрик.

PostgreSQL: NULL replay lag не следует превращать в 0 без проверки stream/LSN.
Возраст `pg_last_xact_replay_timestamp()` сам по себе не является lag при отсутствии нагрузки.
Имя primary в конфигурации — подпись; после failover сопоставление items должно продолжать
следить за текущим лидером и нужной DR-replica, либо его требуется обновить.

SQL Server: учитывайте настроенный restore delay, threshold конкретной БД и результат
последнего завершённого job. Возраст restore и latency восстановленного файла — разные метрики.
Не подменяйте pending_files арифметикой над именами файлов без проверки их состава.

Если items ещё нет, сначала настройте сбор на инфраструктуре: agent/ODBC/external check
для БД, cron/RMAN wrapper для Oracle, Patroni REST API для HA, msdb log-shipping/Agent metadata
для SQL Server. Этот change предоставляет UI и read-only adapter, но не устанавливает коллекторы
на database hosts. Необходимо знать ваши версии, права и существующие Zabbix templates.

## Пороги, свежесть и история

- `warning`/`critical` задаются на metric в **нормализованных единицах**; сравнение `>=`.
  По умолчанию: archive gap/pending apply 1/10 logs; Oracle success age 600/1800 s;
  PG replay lag 10/60 s, WAL backlog 100 MiB/1 GiB; SQL backup/copy age 900/1800 s,
  restore age 1800/5400 s, pending files 1/10.
- `expected_patroni_nodes` — ожидаемое количество исправных узлов (по умолчанию 2).
- `stale_after_seconds` — возраст **измерения Zabbix lastclock**, не последней операции.
  По умолчанию 180 s; для Oracle cron раз в 5 минут в примере 900 s.
  Отключите preprocessing «Discard unchanged» или задайте heartbeat меньше этого порога.
- Состояния pair: CRITICAL → STALE → NO DATA → WARNING → HEALTHY. Известная свежая ошибка
  не скрывается из-за отсутствующей метрики; подробности всех метрик раскрываются под карточкой.
- Browser polling 30/60 s; cache на worker 30 s, включая ошибки. Pause останавливает polling;
  в скрытой вкладке polling не выполняется. Возобновление сразу запрашивает данные.
- Графики: `archive_gap`, `replay_lag`, `restore_age`; numeric history Zabbix за последний час.
  Чтение сгруппировано по value_type (float/unsigned), максимум 10 000 последних точек на тип.
  При большом количестве пар/частоте сбора начало часа может быть усечено. Пропуски >180 s
  не соединяются линией. Отсутствующая история не генерируется искусственно.
- Нет background collector в портале: когда страницу никто не смотрит, историю продолжает
  собирать Zabbix. Live-доступность зависит от его update interval и collector health.

API: [item.get](https://www.zabbix.com/documentation/current/en/manual/api/reference/item/get),
[history.get](https://www.zabbix.com/documentation/current/en/manual/api/reference/history/get).

## Проверка

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests -v
node --check app/static/js/replication.js
```

Тесты используют подставные данные, включая состояния из примеров. Для end-to-end проверки
в production нужны реальные itemid и сетевой доступ приложения к Zabbix.
