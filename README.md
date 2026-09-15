# Hotel Booking Service

Backend-сервис бронирования номеров отеля: REST API поверх PostgreSQL.

Отчёты по лабораторным работам — в каталоге [docs/](docs/), список с описанием ниже.

---

## О проекте

Предметная область — система бронирования отеля. Сервис хранит гостей, номера и их типы,
бронирования, платежи, дополнительные услуги, сотрудников и уборки номеров.
Через API можно вести справочники, создавать и изменять бронирования, добавлять к ним услуги,
принимать платежи и получать аналитические отчёты.

Стек: Python 3.13 / Django 6, PostgreSQL 16, Docker Compose, миграции Django.
ORM используется только для описания схемы и миграций; чтение и запись данных выполняются
обычными SQL-запросами в слое репозиториев, поэтому все запросы доступны для анализа.

---

## Запуск

```bash
docker compose up
```

Поднимается семь контейнеров — базовый сервис плюс инфраструктура, добавленная
лабораторными работами 3–5:

| Сервис             | Порт на хосте | Volume                  | Описание                                                    |
|--------------------|---------------|-------------------------|-------------------------------------------------------------|
| `postgres`         | 5433          | `postgres_data`         | Primary: основная база, секции и pg_cron (лабы 1–3)         |
| `postgres-replica` | 5434          | `postgres_replica_data` | Replica: потоковая репликация, чтение (лаба 4)              |
| `postgres-shard-0` | 5440          | `shard_0_data`          | шард 0 с таблицей `bookings` (лабы 5–6)                     |
| `postgres-shard-1` | 5441          | `shard_1_data`          | шард 1                                                      |
| `postgres-shard-2` | 5442          | `shard_2_data`          | шард 2                                                      |
| `backend`          | 8000          | —                       | Django-приложение с REST API                                |
| `partition-alerts` | —             | —                       | слушатель `LISTEN/NOTIFY` для уведомлений о секциях (лаба 3) |

Внутри сети Docker все базы слушают штатный порт `5432`; разные порты на хосте нужны
только чтобы подключаться к ним снаружи одновременно.

Образ PostgreSQL собирается из [deploy/postgres/Dockerfile](deploy/postgres/Dockerfile):
это `postgres:16-alpine` с собранным из исходников расширением `pg_cron`.

При старте backend ждёт готовности PostgreSQL, автоматически применяет миграции
(`manage.py migrate`) и загружает небольшой демонстрационный набор данных
(`manage.py seed_demo`, идемпотентно; отключается переменной `SEED_DEMO_DATA=false`).

После запуска:

* API — http://localhost:8000/api/bookings
* Health check — http://localhost:8000/health
* Документация Swagger UI — http://localhost:8000/docs
* Спецификация OpenAPI — http://localhost:8000/openapi.yaml

Страница `/docs` подгружает Swagger UI с CDN, поэтому для её отображения нужен интернет;
сама спецификация `/openapi.yaml` отдаётся сервисом локально.

---

## Архитектура

```
Client
  ↓
HTTP-обработчик        main/api/views.py      разбор запроса, коды ответов, JSON
  ↓
Сервисный слой         main/services/*.py     валидация, бизнес-правила
  ↓
Репозиторий            main/repositories/*.py SQL-запросы
  ↓
PostgreSQL
```

* `main/api/views.py`, `main/api/http.py` — контроллеры. К базе напрямую не обращаются.
* `main/services/` — бизнес-логика: проверка дат, пересечений броней, расчёт стоимости,
  валидация входных данных, пагинация.
* `main/repositories/` — единственное место, где выполняется SQL.
  Подключение выбирается в `main/repositories/base.py`: константы `PRIMARY` (`'default'`)
  и `REPLICA` (`'replica'`), функции чтения принимают аргумент `using`, запись всегда
  идёт на Primary (настройки — `booking_service/settings.py`, словарь `DATABASES`).
* `main/sharding/` — router шардирования: `ModuloRouter` и `ConsistentHashRouter`
  (лаба 5); `main/repositories/sharded_booking_repository.py` — SQL к шардам.
* `main/models.py` — описание схемы для системы миграций Django.
* `main/migrations/` — миграции; схема БД никогда не создаётся руками.

---

## Схема БД

```
roomtypes ──1:N──> rooms ──1:N──> bookings <──N:1── guests
                                    │  │
                                    │  └──1:N──> payments
                                    │
                            bookingservices  (M:N: bookings ↔ services)
                                    │
                                 services

employees ──M:N──> employeeroles          (через employeeroleassignments)
employees ──1:N──> roomcleanings <──1:N── rooms
```

| Таблица                   | Назначение                       | Ключи                                              |
|---------------------------|----------------------------------|----------------------------------------------------|
| `roomtypes`               | типы номеров и цена за ночь      | PK `id_type`                                       |
| `rooms`                   | номера отеля                     | PK `id_room`, FK `id_type`                         |
| `guests`                  | гости                            | PK `id_guest`                                      |
| `bookings`                | **бронирования**                 | PK `id_booking`, FK `id_guest`, `id_room`          |
| `services`                | дополнительные услуги            | PK `id_service`                                    |
| `bookingservices`         | услуги в брони (**many-to-many**)| PK (`id_booking`, `id_service`), FK на обе таблицы |
| `payments`                | платежи по броням                | PK `id_payment`, FK `id_booking`                   |
| `employees`               | сотрудники                       | PK `id_employee`                                   |
| `employeeroles`           | роли сотрудников                 | PK `id_role`                                       |
| `employeeroleassignments` | роли сотрудников (**many-to-many**) | PK (`id_employee`, `id_role`)                   |
| `roomcleanings`           | уборки номеров                   | PK `id_cleaning`, FK `id_room`, `id_employee`      |

Связи one-to-many: `roomtypes → rooms`, `guests → bookings`, `rooms → bookings`,
`bookings → payments`, `rooms → roomcleanings`, `employees → roomcleanings`.
Связи many-to-many: `bookings ↔ services`, `employees ↔ employeeroles`.

Временные поля: `bookings.created_at`, `bookings.updated_at`, `guests.created_at`,
`payments.created_at`.

### Индексы

Помимо индексов, которые Django создаёт автоматически (первичные ключи, `UNIQUE`-поля
и внешние ключи), в миграции `0002` добавлены индексы под реальные запросы API
к основной растущей сущности `bookings`:

| Индекс | Колонки | Какой запрос обслуживает |
|---|---|---|
| `idx_bookings_created_at` | `(created_at DESC)` | `GET /api/bookings` — лента без фильтров, сортировка по умолчанию `created_at DESC`; фильтры `?created_from` / `?created_to` |
| `idx_bookings_status_created` | `(status, created_at DESC)` | `GET /api/bookings?status=...` — фильтр по статусу + сортировка + `LIMIT` |
| `idx_bookings_status_check_in` | `(status, check_in)` | `GET /api/bookings?status=...&check_in_from=...&check_in_to=...` — выборки заездов за период |

Порядок колонок везде один и тот же: сначала условие равенства (`status`), затем
колонка диапазона или сортировки. Это позволяет PostgreSQL брать из индекса и
фильтрацию, и готовый порядок строк, и останавливать чтение после `LIMIT`.

Индексы объявлены в `Meta.indexes` модели `Booking` (`main/models.py`), поэтому
создаются автоматически при `manage.py migrate` — то есть на любой чистой базе.

Замеры до/после, планы выполнения и обоснование выбора — в
[docs/lab-01-indexes.md](docs/lab-01-indexes.md) (лабораторная работа №1, задания 22–30).

---

## Основная сущность для масштабирования

```
bookings
```

**Почему она подходит:**

* Это центральная операционная таблица: каждая продажа отеля — новая строка,
  количество записей растёт постоянно и неограниченно, тогда как справочники
  (`rooms`, `roomtypes`, `services`) практически не меняются в размере.
* От неё зависят другие растущие таблицы — `payments` и `bookingservices`,
  поэтому нагрузка распространяется на связанные сущности.
* У неё есть естественное временное поле `created_at`, по которому данные удобно
  разбивать на диапазоны (партиционирование по времени).
* Основные пользовательские сценарии — это чтение списка броней с фильтрами,
  JOIN со справочниками и агрегаты по периодам, то есть именно те запросы,
  которые деградируют при росте объёма.

---

## Лабораторные работы

Каждая работа выполнена на этом сервисе; отчёты лежат в [docs/](docs/).

| № | Отчёт | Тема | Что добавилось в проект |
| --- | --- | --- | --- |
| 1 | [lab-01-indexes.md](docs/lab-01-indexes.md) | Индексы и `EXPLAIN ANALYZE` | индексы в `Meta.indexes` модели `Booking`, миграция `0002` |
| 2 | [lab-02-data-growth.md](docs/lab-02-data-growth.md) | Деградация при росте данных | схема `lab2`, замеры на таблице `events`; команда `generate_data` |
| 3 | [lab-03-partitioning.md](docs/lab-03-partitioning.md) | Партиционирование и автоматизация через `pg_cron` | схема `lab3`, [10-partitions-pg-cron.sql](deploy/postgres/initdb/10-partitions-pg-cron.sql), команды `create_partitions`, `check_partitions`, `partition_alert_listener` |
| 4 | [lab-04-read-scaling.md](docs/lab-04-read-scaling.md) | Масштабирование чтения: Primary + Replica | сервис `postgres-replica`, [replica-entrypoint.sh](deploy/postgres/replica-entrypoint.sh), `DATABASES['replica']`, команда `replication_status` |
| 5 | [lab-05-sharding.md](docs/lab-05-sharding.md) | Шардирование: router и consistent hashing | три шарда, [main/sharding/](main/sharding/), `sharded_booking_repository.py`, команда `shard_bookings` |
| 6 | [lab-06-sharded-queries.md](docs/lab-06-sharded-queries.md) | Запросы сервиса после шардирования | команда `shard_queries` (single / count / join / top / hot / failure) |

Шардируемая сущность — `bookings`, ключ шардирования — `id_guest` (горизонтальное
шардирование по хешу ключа). Справочники `guests`, `rooms`, `roomtypes` и таблица
`payments` остаются в основной базе, поэтому API работает с ней, а шарды используются
командами лабораторных работ 5–6.

---

## Основные endpoint'ы

### Служебные

| Метод | Путь            | Описание                                   |
|-------|-----------------|--------------------------------------------|
| GET   | `/health`       | Состояние сервиса и подключения к PostgreSQL |
| GET   | `/docs`         | Swagger UI                                 |
| GET   | `/openapi.yaml` | Спецификация OpenAPI 3.0                   |

### Бронирования (основная сущность)

| Метод  | Путь                                         | Описание                        |
|--------|----------------------------------------------|---------------------------------|
| GET    | `/api/bookings`                              | список с пагинацией/фильтрами   |
| POST   | `/api/bookings`                              | создать бронирование            |
| GET    | `/api/bookings/{id}`                         | карточка брони                  |
| PUT    | `/api/bookings/{id}`                         | изменить бронирование           |
| DELETE | `/api/bookings/{id}`                         | удалить бронирование            |
| GET    | `/api/bookings/{id}/services`                | услуги брони                    |
| POST   | `/api/bookings/{id}/services`                | добавить услугу в бронь         |
| DELETE | `/api/bookings/{id}/services/{service_id}`   | убрать услугу из брони          |
| GET    | `/api/bookings/{id}/payments`                | платежи по брони                |

### Справочники и связанные сущности

| Метод                  | Путь                          | Описание                    |
|------------------------|-------------------------------|-----------------------------|
| GET/POST               | `/api/guests`                 | гости                       |
| GET/PUT/DELETE         | `/api/guests/{id}`            | гость                       |
| GET                    | `/api/guests/{id}/bookings`   | бронирования гостя          |
| GET/POST               | `/api/rooms`                  | номера                      |
| GET/PUT/DELETE         | `/api/rooms/{id}`             | номер                       |
| GET                    | `/api/rooms/{id}/bookings`    | бронирования номера         |
| GET/POST               | `/api/room-types`             | типы номеров                |
| GET/PUT/DELETE         | `/api/room-types/{id}`        | тип номера                  |
| GET/POST               | `/api/services`               | услуги                      |
| GET/PUT/DELETE         | `/api/services/{id}`          | услуга                      |
| GET/POST               | `/api/payments`               | платежи                     |
| GET/PUT/DELETE         | `/api/payments/{id}`          | платёж                      |

### Отчёты (агрегация)

| Метод | Путь                                    | Описание                          |
|-------|-----------------------------------------|-----------------------------------|
| GET   | `/api/reports/revenue-by-room-type`     | выручка по типам номеров          |
| GET   | `/api/reports/top-guests`               | гости с наибольшей суммой броней  |

### Pagination, filtering, sorting

`GET /api/bookings` поддерживает:

* пагинацию: `?page=2&page_size=50`;
* фильтры: `?status=confirmed`, `?guest_id=1`, `?room_id=3`, `?room_type_id=2`,
  `?check_in_from=2026-01-01&check_in_to=2026-02-01`,
  `?created_from=2026-01-01&created_to=2026-01-31`;
* поиск: `?search=Иванов` (ILIKE по фамилии/имени гостя и номеру комнаты);
* сортировку: `?sort=created_at`, `?sort=-created_at`, `?sort=-total_price`.

Пример:

```bash
curl "http://localhost:8000/api/bookings?status=confirmed&search=Иванов&sort=-created_at&page=1&page_size=20"
```

Пагинация и фильтры также доступны у `/api/guests`, `/api/rooms`, `/api/room-types`,
`/api/services`, `/api/payments`.

---

## Сложные запросы

### JOIN-запрос №1 — список бронирований

`GET /api/bookings` — `main/repositories/booking_repository.py`, `list_bookings()`.
Соединяет бронирования со справочниками, поддерживает фильтры, поиск, сортировку и LIMIT/OFFSET.

```sql
SELECT b.id_booking, b.check_in, b.check_out, b.total_price, b.status, b.created_at,
       g.id_guest, g.last_name AS guest_last_name, g.first_name AS guest_first_name,
       r.id_room, r.room_number, r.floor,
       rt.id_type, rt.name AS room_type, rt.price_per_night
FROM bookings b
JOIN guests g     ON g.id_guest = b.id_guest
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
WHERE b.status = %s
  AND b.check_in >= %s
  AND (g.last_name ILIKE %s OR g.first_name ILIKE %s OR r.room_number ILIKE %s)
ORDER BY b.created_at DESC
LIMIT %s OFFSET %s;
```

### JOIN-запрос №2 — карточка брони с суммой платежей

`GET /api/bookings/{id}` — `main/repositories/booking_repository.py`, `get_booking()`.
Четыре таблицы плюс LEFT JOIN на платежи с агрегатом.

```sql
SELECT b.id_booking, b.check_in, b.check_out, b.total_price, b.status, b.created_at,
       g.last_name, g.first_name, g.email, g.phone,
       r.room_number, r.floor,
       rt.name AS room_type, rt.price_per_night,
       COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'success'), 0) AS paid_amount,
       COUNT(p.id_payment) AS payments_count
FROM bookings b
JOIN guests g     ON g.id_guest = b.id_guest
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
LEFT JOIN payments p ON p.id_booking = b.id_booking
WHERE b.id_booking = %s
GROUP BY b.id_booking, g.id_guest, r.id_room, rt.id_type;
```

### JOIN-запрос №3 — услуги брони (many-to-many)

`GET /api/bookings/{id}/services` — `list_services_of_booking()`.

```sql
SELECT s.id_service, s.name, s.price, bs.quantity,
       (bs.quantity * s.price) AS line_total,
       b.id_booking, b.status AS booking_status
FROM bookingservices bs
JOIN services s ON s.id_service = bs.id_service
JOIN bookings b ON b.id_booking = bs.id_booking
WHERE bs.id_booking = %s
ORDER BY s.name;
```

### Агрегирующий запрос — выручка по типам номеров

`GET /api/reports/revenue-by-room-type` — `main/repositories/report_repository.py`.

```sql
SELECT rt.id_type,
       rt.name AS room_type,
       COUNT(b.id_booking)                        AS bookings_count,
       COALESCE(SUM(b.total_price), 0)            AS total_revenue,
       COALESCE(AVG(b.total_price), 0)            AS average_price,
       MIN(b.total_price)                         AS min_price,
       MAX(b.total_price)                         AS max_price,
       COALESCE(SUM(b.check_out - b.check_in), 0) AS total_nights
FROM bookings b
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
WHERE b.created_at >= %s AND b.created_at <= %s
GROUP BY rt.id_type, rt.name
ORDER BY total_revenue DESC;
```

### Агрегирующий запрос — топ гостей

`GET /api/reports/top-guests` — `top_guests()`: `GROUP BY` по гостю с `COUNT`, `SUM`, `AVG`,
`MAX` и `HAVING`.

---

## Генерация данных

Демонстрационный набор (загружается автоматически при `docker compose up`):

```bash
docker compose exec backend python manage.py seed_demo
```

Массовая генерация — данные создаются полностью внутри PostgreSQL
(`INSERT ... SELECT generate_series`), поэтому миллионы строк вставляются быстро:

```bash
# 100 000 гостей и 1 000 000 бронирований
docker compose exec backend python manage.py generate_data \
    --rooms 500 --guests 100000 --bookings 1000000

# полный набор с очисткой предыдущих данных
docker compose exec backend python manage.py generate_data --truncate \
    --rooms 500 --guests 100000 --bookings 1000000 \
    --payments 500000 --booking-services 300000
```

Параметры команды:

| Параметр              | Описание                                                        |
|-----------------------|-----------------------------------------------------------------|
| `--guests N`          | сколько гостей создать                                          |
| `--rooms N`           | сколько номеров создать                                         |
| `--bookings N`        | сколько бронирований создать                                    |
| `--payments N`        | сколько платежей создать (по случайным броням)                  |
| `--booking-services N`| сколько связей «бронь — услуга» создать                         |
| `--batch-size N`      | размер пачки вставки, по умолчанию 50 000                       |
| `--truncate`          | очистить `bookings`, `payments`, `bookingservices`, `guests`, `rooms` |

`created_at` у сгенерированных бронирований распределён по последним двум годам,
что удобно для последующих экспериментов с партиционированием по времени.

---

## Полезные команды

```bash
docker compose up --build        # запуск
docker compose ps                # состояние контейнеров
docker compose logs -f backend   # логи приложения
docker compose down              # остановить, данные в volume сохраняются
docker compose exec backend python manage.py migrate          # миграции вручную
docker compose exec postgres psql -U booking booking_service  # psql на Primary
docker compose exec postgres-replica psql -U booking booking_service  # psql на Replica
docker compose exec postgres-shard-0 psql -U booking booking_shard   # psql на шарде
```

> `docker compose down -v` удаляет volume'ы вместе со всеми данными — основной базой,
> репликой и шардами. После этого данные лабораторных работ придётся генерировать заново.

Команды лабораторных работ:

```bash
# лаба 3 — секции
docker compose exec backend python manage.py create_partitions
docker compose exec backend python manage.py check_partitions
docker compose exec postgres psql -U booking booking_service -c "SELECT * FROM cron.job;"

# лаба 4 — репликация
docker compose exec backend python manage.py replication_status
docker compose exec backend python manage.py replication_status --probe 5

# лаба 5 — шарды
docker compose exec backend python manage.py shard_bookings load
docker compose exec backend python manage.py shard_bookings stats
docker compose exec backend python manage.py shard_bookings route --guest 29604
docker compose exec backend python manage.py shard_bookings rebalance

# лаба 6 — запросы к шардам
docker compose exec backend python manage.py shard_queries single
docker compose exec backend python manage.py shard_queries count
docker compose exec backend python manage.py shard_queries join
docker compose exec backend python manage.py shard_queries top --limit 10
docker compose exec backend python manage.py shard_queries hot
docker compose exec backend python manage.py shard_queries failure
```

Локальный запуск без Docker (нужен доступный PostgreSQL):

```bash
pip install -r requirements.txt
export POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_DB=booking_service \
       POSTGRES_USER=booking POSTGRES_PASSWORD=booking
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

`POSTGRES_PORT=5433` — это порт, на который контейнер `postgres` проброшен на хост.
Если PostgreSQL установлен на машине напрямую, укажите его собственный порт.
