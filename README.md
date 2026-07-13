# DBA Inventory MVP

MVP веб-портала для инвентаризации DBA: хосты, инстансы СУБД, HA-кластеры, Zabbix-связки, PoWA-связки, фильтры и Excel-экспорт.

## Стек

- Backend: Python FastAPI
- Frontend: Jinja2 + Bootstrap
- Database: PostgreSQL
- ORM: SQLAlchemy
- Migrations: Alembic
- Export: Excel через openpyxl
- Deployment: Docker Compose

## Структура проекта

```text
app/
  core/              # настройки приложения
  db/                # SQLAlchemy engine/session/Base
  models/            # Host, DatabaseInstance, Cluster, ClusterMember
  routers/           # dashboard, hosts, databases, clusters, exports
  static/css/        # CSS поверх Bootstrap
  templates/         # Jinja2 страницы
  main.py            # FastAPI application
  seed.py            # демо-данные
alembic/
  versions/          # миграции
docker-compose.yml
Dockerfile
requirements.txt
```

## Быстрый запуск через Docker Compose

```bash
docker compose up --build
```

Приложение будет доступно по адресу:

```text
http://localhost:8000
```

Контейнерный PostgreSQL не публикуется на порт `5432` хоста, чтобы не конфликтовать с существующим PostgreSQL на сервере. Приложение подключается к нему внутри Docker-сети по имени сервиса `db`.

## Запуск на Ubuntu из GitHub

1. Установите Docker Engine и Compose plugin на Ubuntu.

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

2. Склонируйте репозиторий и запустите портал.

```bash
git clone https://github.com/adiaadi/dba-inventory.git
cd dba-inventory
cp .env.example .env
docker compose up -d --build
```

Можно также использовать готовый скрипт:

```bash
bash scripts/ubuntu-run.sh
```

3. Проверьте состояние контейнеров.

```bash
docker compose ps
docker compose logs -f app
```

При старте контейнер приложения выполняет:

```bash
alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Локальный запуск без Docker

1. Создайте и активируйте виртуальное окружение.

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Установите зависимости.

```bash
pip install -r requirements.txt
```

3. Создайте БД PostgreSQL и задайте строку подключения.

```bash
copy .env.example .env
set DATABASE_URL=postgresql+psycopg://dba_inventory:dba_inventory@localhost:5432/dba_inventory
```

4. Примените миграции и загрузите демо-данные.

```bash
alembic upgrade head
python -m app.seed
```

5. Запустите приложение.

```bash
uvicorn app.main:app --reload
```

## Основные страницы

- `/` - Dashboard
- `/hosts` - список серверов
- `/databases` - список СУБД и инстансов
- `/clusters` - Patroni / Oracle Standby / SQL Server Log Shipping
- `/exports/hosts.xlsx` - экспорт хостов в Excel
- `/exports/databases.xlsx` - экспорт БД в Excel

## Фильтры

На страницах `Hosts`, `Databases` и `Clusters` доступны фильтры:

- DB type
- environment
- role
- monitoring status

Те же query-параметры применяются к Excel-экспорту.

## Модель данных

- `hosts`: серверы и поля интеграции с Zabbix (`zabbix_hostid`, `zabbix_host_name`, `zabbix_url`, `monitoring_status`)
- `database_instances`: СУБД/инстансы и поля интеграции с PoWA (`powa_repository`, `powa_server_name`, `powa_database_name`, `last_snapshot`, `status`)
- `clusters`: HA-кластеры и их состояние
- `cluster_members`: связь кластера с инстансами БД и ролью узла
