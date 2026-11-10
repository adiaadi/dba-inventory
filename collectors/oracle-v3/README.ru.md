# Oracle v3: CBSETL, CAPETL, DWH на CBS-DR-DB

Комплект подготовлен из переданных рабочих файлов stage2. На сервере не установлен.
Предназначен для одного redo thread (thread 1), mounted physical standby.
Проверки metadata/SCN, SHA-256, инкарнации и ошибок RMAN сохранены.

| SID | SSH primary | Архивы primary | Архивы standby | Формат |
|---|---|---|---|---|
| CBSETL | cbs-prod-db | /oradata/backup/CBSETL_seed | /u01/arch/CBSETL_seed | 1_SEQ_RESETLOGS.dbf |
| CAPETL | cap-prod-db | /oradata/backup/CAPETL_seed | /u01/arch/CAPETL_seed | SEQ_1_RESETLOGS.arc |
| DWH | dwh-prod-db | /oradata/archive | /u01/arch/DWH_seed | 1_SEQ_RESETLOGS.dbf |

CBS-PROD-DB01 остаётся подписью портала, SSH-адрес cbs-prod-db взят из рабочего
monitor.py. Для CAPETL перенос теперь выбирает только thread 1 текущего RESETLOGS_ID.
Каталоги и SID primary взяты из исходных скриптов; подтвердите их через inspect/probe.

## 1. Установка рядом с v2

Передайте каталог `collectors/oracle-v3` на CBS-DR-DB, затем из него:

```bash
python3 -m unittest discover -s . -p 'test_*.py' -v
bash -n run.sh
bash -n sync_seed_arch.monitored.sh
bash -n restore_arch_notify.monitored.sh
sudo install -d -o root -g root -m 0755 /opt/db-inv-oracle-v3
sudo install -m 0644 monitor.py archives.py /opt/db-inv-oracle-v3/
sudo install -m 0755 run.sh sync_seed_arch.monitored.sh restore_arch_notify.monitored.sh /opt/db-inv-oracle-v3/
# Только для первой установки: не затирать уже заполненные DBID повторным копированием.
sudo test -e /opt/db-inv-oracle-v3/databases.json || sudo install -m 0644 databases.json /opt/db-inv-oracle-v3/
```

## 2. Проверить базы без переноса и recovery

```bash
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh inspect CAPETL
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh inspect DWH
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh inspect CBSETL
```

`inspect` выполняет SELECT на standby и primary, сверяет идентичность и проверяет
standby headers. Ничего не пишет, не копирует и не запускает RMAN.
Для CAPETL/DWH `dbid` и `header_count` в databases.json пока null.
После проверки вывода заполните их значениями standby через:

```bash
sudoedit /opt/db-inv-oracle-v3/databases.json
```

Не переносите DBID и 16 datafiles от CBSETL в другие базы. `run` и `probe`
отклоняются, пока эти поля не заполнены положительными целыми числами.
Затем для каждой базы:

```bash
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh probe CAPETL
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh probe DWH
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh probe CBSETL
```

`probe` дополнительно читает/хеширует архивы; manifest/state не сохраняет.
Проверять между существующими циклами: изменение файлов во время хеширования
может дать ошибку. Если последняя применённая копия уже удалена, copied_seq
может быть null до первой подтверждённой новой копии.

## 3. Переключать по одной базе

Сначала сохраните crontab oracle и отключите старую цепочку только выбранного SID.
Дождитесь завершения её процессов. Не добавляйте v3 рядом с работающей старой
cron-цепочкой: старые sync/restore имеют отдельные locks, которые не защищают
весь промежуток между переносом, аудитом и recovery.

Для каждого SID создайте каталог состояния; группа zabbix должна существовать:

```bash
sudo install -d -o oracle -g zabbix -m 2750 /var/lib/db-inv-oracle/CAPETL
sudo install -d -o oracle -g zabbix -m 2750 /var/lib/db-inv-oracle/DWH
# Для существующего CBSETL сохраните владельца oracle и обеспечьте чтение группе zabbix.
sudo install -d -o oracle -g zabbix -m 2750 /var/lib/db-inv-oracle/CBSETL
```

Состояние: `<SID>/state-v3.json`, подтверждения: `<SID>/manifest-v3.json`.
Chain lock: `<SID>/chain.lock`, общий с v2 для соответствующего SID.
V2 state/manifest не перезаписываются. Новый manifest начинает отдельный аудит.

Следующая команда действительно выполняет перенос и RMAN для выбранной базы:

```bash
sudo -iu oracle /bin/bash /opt/db-inv-oracle-v3/run.sh run CAPETL
sudo -u zabbix /usr/bin/python3 /opt/db-inv-oracle-v3/monitor.py read --sid CAPETL
```

После успешной проверки замените старую команду CAPETL в cron, сохранив её расписание:

```text
/bin/bash /opt/db-inv-oracle-v3/run.sh run CAPETL >>/home/oracle/log/db_inv_CAPETL.log 2>&1
```

Аналогично для DWH и CBSETL, с соответствующим SID. Новое расписание не навязывается.
Скрипты restore сохраняют прежний механизм уведомлений, если настроены TG-переменные.
Ошибки не превращаются в SUCCESS; source snapshot истекает через 600 секунд.

## 4. Zabbix

```bash
sudo install -m 0644 db-inv-oracle-v3.conf /etc/zabbix/zabbix_agent2.d/db-inv-oracle-v3.conf
sudo zabbix_agent2 -T
# Выполнять перезапуск только после успешного -T:
sudo systemctl restart zabbix-agent2
sudo -u zabbix zabbix_agent2 -t 'db.replication.oracle.raw[CAPETL]'
sudo -u zabbix zabbix_agent2 -t 'db.replication.oracle.raw[DWH]'
sudo -u zabbix zabbix_agent2 -t 'db.replication.oracle.raw[CBSETL]'
```

Импортируйте `zabbix-template-8.0.json` и привяжите нужные новые шаблоны к
техническому хосту `cbs-dr-db`. В комплекте три шаблона с отдельными UUID и keys.
Не используйте Delete missing. Старый шаблон CBSETL и его история остаются;
после перехода отключите старые items/triggers, чтобы они не выдавали stale alerts.
Новые items начинают собственную историю. Agent active checks требуют корректного
Hostname/ServerActive, как и исходный шаблон. Actions/получатели не создаются.

Пример keys: `db.replication.oracle.raw[CAPETL]`,
`db.replication.oracle.applied_seq[CAPETL]`. UserParameters статические, без
подстановки произвольных аргументов агента. `read` только читает JSON, без Oracle/SSH.

## 5. Портал

`replication.json` рядом с этой инструкцией содержит все три пары с новыми keys.
После появления данных в Zabbix перенесите пары в рабочий config/replication.json
портала, сохранив остальные пары/локальные пороги. Во время поэтапного перехода
заменяйте только пару уже переключённого SID; CBSETL может продолжать использовать
старые keys без параметра до своего перехода.
Не заменяйте рабочий JSON на полный v3 заранее: старые keys отличаются.
Коллектор находится на CBS-DR-DB, а не в контейнере приложения портала.

## Откат

Отключите v3 cron выбранного SID и дождитесь завершения процессов. Восстановите
сохранённую старую команду и старые keys этой пары в портале. Отключите её v3
items/triggers. Не удаляйте state/manifest ни v2, ни v3.

## Проверки

Локальные unit tests проверяют очередь, SCN, хеши, ошибки transfer/RMAN,
изоляцию профилей, блокировку непроверенного run и соответствие keys шаблонов
порталу. Они не заменяют Linux/Oracle probe, импорт шаблонов и проверку прав
на рабочем сервере. Сборщик ничего не развёртывает автоматически.
