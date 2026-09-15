# Лабораторная работа №4
# Масштабирование чтения PostgreSQL: Primary + Replica

Оба экземпляра — PostgreSQL 16.13 в Docker, собранные из одного образа
`booking-postgres-pgcron` (лаба 3). Репликация — потоковая (streaming replication),
асинхронная. Эксперименты выполнены 2026-09-13 по UTC; время в выводах серверов — UTC.

## Что получилось

| Требование | Результат |
|---|---|
| Primary — принимает INSERT / UPDATE / DELETE | `booking_postgres`, порт 5433 на хосте |
| Replica — копия для чтения | `booking_postgres_replica`, порт 5434, hot standby |
| Streaming replication | `pg_stat_replication`: `state = streaming`, `sync_state = async`, слот `replica_1` |
| Изменение с Primary появляется на Replica | INSERT, UPDATE и DELETE проверены, LSN совпадают |
| Read-сценарий сервиса через Replica | `GET /api/bookings` (список + COUNT для пагинации) читается из подключения `replica` |
| Replication lag зафиксирован | 175 из 200 первых SELECT после INSERT увидели старые данные; под нагрузкой отставание доходило до 20 МБ WAL |

---

## Часть 1. Primary и Replica

### Фрагмент docker-compose.yml

Полный файл — [docker-compose.yml](docker-compose.yml). Здесь только то, что относится к репликации.

```yaml
services:
  # Primary: принимает все записи и отдаёт поток WAL реплике
  postgres:
    build: ./deploy/postgres
    image: booking-postgres-pgcron
    container_name: booking_postgres
    command:
      - postgres
      # ... параметры pg_cron из лабы 3 ...
      - -c
      - hba_file=/etc/postgresql/pg_hba.conf      # правила доступа из репозитория
      - -c
      - wal_level=replica                         # в WAL пишется всё, что нужно реплике
      - -c
      - max_slot_wal_keep_size=2GB                # лимит WAL, удерживаемого слотом
    environment:
      REPLICATION_USER: replicator
      REPLICATION_PASSWORD: replicator
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./deploy/postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro
      - ./deploy/postgres/initdb:/docker-entrypoint-initdb.d:ro

  # Replica: hot standby, только чтение
  postgres-replica:
    image: booking-postgres-pgcron
    container_name: booking_postgres_replica
    entrypoint: ["replica-entrypoint.sh"]         # при пустом томе снимает копию с Primary
    command:
      - postgres
      - -c
      - max_worker_processes=20                   # не меньше, чем на Primary
      - -c
      - hba_file=/etc/postgresql/pg_hba.conf
      - -c
      - hot_standby=on                            # принимать read-only подключения
      - -c
      - log_min_duration_statement=0              # логировать каждый запрос (для части 5)
      - -c
      - "log_line_prefix=%m [%p] app=%a db=%d "
    environment:
      PRIMARY_HOST: postgres
      PRIMARY_PORT: "5432"
      REPLICATION_USER: replicator
      REPLICATION_PASSWORD: replicator
      REPLICATION_SLOT: replica_1
    ports:
      - "5434:5432"
    volumes:
      - postgres_replica_data:/var/lib/postgresql/data
      - ./deploy/postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro
    depends_on:
      postgres:
        condition: service_healthy

  backend:
    environment:
      POSTGRES_HOST: postgres                     # Primary — записи и чтение по умолчанию
      POSTGRES_REPLICA_HOST: postgres-replica     # Replica — список бронирований
```

### Какой контейнер что делает

| Контейнер | Роль | Порт на хосте | Том с данными | Размер данных |
|---|---|---|---|---|
| `booking_postgres` | **Primary** | 5433 | `postgres_data` | 3.1 ГБ |
| `booking_postgres_replica` | **Replica** (hot standby) | 5434 | `postgres_replica_data` | 3.0 ГБ |

```
NAME                       IMAGE                     PORTS                    STATUS
booking_backend            booking_service-backend   0.0.0.0:8000->8000/tcp   Up
booking_postgres           booking-postgres-pgcron   0.0.0.0:5433->5432/tcp   Up (healthy)
booking_postgres_replica   booking-postgres-pgcron   0.0.0.0:5434->5432/tcp   Up (healthy)
```

Кто есть кто, база отвечает сама:

```sql
SELECT pg_is_in_recovery();   -- Primary: f     Replica: t
```

### Как подключиться

```bash
# изнутри Docker
docker exec -it -e PGPASSWORD=booking booking_postgres         psql -U booking -d booking_service
docker exec -it -e PGPASSWORD=booking booking_postgres_replica psql -U booking -d booking_service

# с хоста
psql -h localhost -p 5433 -U booking -d booking_service    # Primary
psql -h localhost -p 5434 -U booking -d booking_service    # Replica
```

Из backend-контейнера Primary доступен по имени `postgres:5432`, Replica — `postgres-replica:5432`.

### Два подводных камня при подъёме

**Один и тот же образ для обоих узлов.** Реплика — побайтовая копия каталога данных Primary,
поэтому версия PostgreSQL и системная библиотека должны совпадать. Образ построен на Alpine
(musl); Debian-образ (glibc) сортирует строки иначе, и текстовые индексы скопированной базы
стали бы некорректными.

**`max_worker_processes` на Replica не меньше, чем на Primary.** Primary работает с
`max_worker_processes=20` (лаба 3). Hot standby с меньшим значением не стартует — PostgreSQL
проверяет это при запуске, потому что настройки, влияющие на разделяемую память, должны быть
не ниже, чем у сервера, чей WAL воспроизводится.

---

## Часть 2. Streaming replication

### Цепочка

```
Primary                                                  Replica
───────                                                  ───────
клиент: INSERT / UPDATE / DELETE
      ↓
изменение записывается в WAL                             
(журнал предзаписи, pg_wal/)                             
      ↓ COMMIT = запись WAL на диск                      
процесс walsender ──── поток WAL по сети ────►  процесс walreceiver
                        (порт 5432, роль                  ↓ записывает в свой pg_wal/
                         replicator)                      ↓
                                                         startup-процесс воспроизводит
                                                         записи WAL → данные меняются
                                                          ↓
                                                         SELECT видит изменение
```

Реплика **не получает SQL** и не выполняет запросы приложения повторно. Она получает тот же
журнал изменений блоков, который Primary пишет для собственного восстановления после сбоя,
и применяет его к своей копии данных. Поэтому реплика всегда логически идентична Primary
на момент воспроизведённого LSN и не может расходиться с ним.

### Что понадобилось настроить

**1. Роль для репликации.** Атрибут `REPLICATION` разрешает открывать replication-подключения
и читать WAL, но не даёт прав на данные. На пустом томе роль создаёт скрипт
[deploy/postgres/initdb/00-replication.sh](deploy/postgres/initdb/00-replication.sh);
на существующей базе тот же SQL выполнен вручную:

```sql
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';
```

```
  rolname   | rolreplication | rolsuper | rolcanlogin
------------+----------------+----------+-------------
 replicator | t              | f        | t
```

**2. Правило в pg_hba.conf.** Строка `host all all all scram-sha-256`, которую генерирует
образ, replication-подключения **не разрешает**: `replication` в колонке database — отдельное
ключевое слово, а не имя базы. Добавлена строка
([deploy/postgres/pg_hba.conf:22](deploy/postgres/pg_hba.conf#L22)):

```
host    replication     all             all             scram-sha-256
```

Файл лежит в репозитории и подключается параметром `hba_file`, поэтому действует и на
существующем томе, где `pg_hba.conf` внутри каталога данных менять было бы невоспроизводимо.
Проверка на Primary:

```
SELECT line_number, type, database, user_name, address, auth_method FROM pg_hba_file_rules;

 line_number | type  |   database    | user_name | address |  auth_method
-------------+-------+---------------+-----------+---------+---------------
          17 | host  | {all}         | {all}     | all     | scram-sha-256
          22 | host  | {replication} | {all}     | all     | scram-sha-256
```

**3. Параметры Primary.** `wal_level=replica` (значение по умолчанию, задано явно) и
`max_slot_wal_keep_size=2GB`. Слот репликации заставляет Primary хранить WAL, пока реплика
его не забрала — иначе после долгой остановки реплики нужные сегменты были бы удалены и
реплику пришлось бы пересоздавать. Лимит защищает диск Primary, если реплика остановлена
надолго. `max_wal_senders=10` и `max_replication_slots=10` — значения по умолчанию.

**4. Загрузка реплики.** При первом старте [deploy/postgres/replica-entrypoint.sh](deploy/postgres/replica-entrypoint.sh)
видит пустой каталог данных и снимает базовую копию:

```sh
pg_basebackup --host=postgres --username=replicator --pgdata="$PGDATA" \
    --format=plain --wal-method=stream --checkpoint=fast --progress \
    --create-slot --slot=replica_1 \
    --write-recovery-conf
```

- `--wal-method=stream` — параллельно с копированием файлов забирать WAL, чтобы копия была
  согласованной;
- `--create-slot --slot=replica_1` — создать слот на Primary и привязать к нему реплику;
- `--write-recovery-conf` — записать в каталог данных `standby.signal` и `primary_conninfo`.
  Именно эти два элемента превращают копию в реплику: при старте сервер видит
  `standby.signal`, входит в режим восстановления и по `primary_conninfo` подключается
  к Primary за WAL.

Копия 2.4 ГБ заняла около 6 секунд:

```
Каталог данных пуст — снимаю базовую копию с Primary postgres:5432...
1087079/2404118 kB (45%), 0/1 tablespace
2404128/2404128 kB (100%), 1/1 tablespace
Базовая копия готова, сервер стартует как hot standby.
LOG:  entering standby mode
LOG:  starting backup recovery with redo LSN 3/78000028, checkpoint LSN 3/78000060, on timeline ID 1
LOG:  consistent recovery state reached at 3/78000100
LOG:  started streaming WAL from primary at 3/79000000 on timeline 1
```

Что появилось в каталоге данных реплики:

```
-rw------- postgres postgres 0  standby.signal
postgresql.auto.conf:
  primary_conninfo = 'user=replicator password=*** host=postgres port=5432 ...'
  primary_slot_name = 'replica_1'
```

При последующих запусках каталог уже не пуст, и entrypoint сразу передаёт управление
штатному запуску сервера — копия не снимается повторно.

### Состояние репликации на Primary

```sql
SELECT * FROM pg_stat_replication;
```

```
pid              | 98
usename          | replicator
application_name | walreceiver
client_addr      | 172.29.0.4
state            | streaming
sync_state       | async
sent_lsn         | 3/79000000
write_lsn        | 3/79000000
flush_lsn        | 3/79000000
replay_lsn       | 3/79000000
write_lag        | 00:00:00.000056
flush_lag        | 00:00:00.000056
replay_lag       | 00:00:00.000056
```

Как читать: `state = streaming` — реплика подключена и получает WAL непрерывно;
`sync_state = async` — Primary не ждёт подтверждения от реплики при COMMIT (отсюда и
возможен lag, часть 6). Четыре LSN — это позиции в журнале: сколько Primary отправил
(`sent`), сколько реплика записала на диск (`write`), сбросила (`flush`) и воспроизвела
(`replay`). Разница между `sent_lsn` и `replay_lsn` — отставание в байтах.

Слот и приёмник на реплике:

```
 slot_name | slot_type | active | restart_lsn | wal_status
-----------+-----------+--------+-------------+------------
 replica_1 | physical  | t      | 3/79000000  | reserved

pg_stat_wal_receiver: status = streaming, sender_host = postgres, slot_name = replica_1
```

---

## Часть 3. Доказательство, что репликация работает

Таблица `services` сервиса. Все операции записи — на Primary, все SELECT — на Replica.

**INSERT на Primary:**

```sql
INSERT INTO services (name, description, price)
VALUES ('Тест репликации', 'Строка для лабораторной №4', 1.00) RETURNING *;

 id_service |      name       |        description         | price
------------+-----------------+----------------------------+-------
          5 | Тест репликации | Строка для лабораторной №4 |  1.00
```

**SELECT на Replica:**

```sql
SELECT id_service, name, description, price FROM services WHERE name = 'Тест репликации';

 id_service |      name       |        description         | price
------------+-----------------+----------------------------+-------
          5 | Тест репликации | Строка для лабораторной №4 |  1.00
```

**UPDATE на Primary → SELECT на Replica:**

```
UPDATE services SET price = 2.50, description = 'Обновлено на Primary' WHERE name = 'Тест репликации';

Replica:
 id_service |      name       |     description      | price
------------+-----------------+----------------------+-------
          5 | Тест репликации | Обновлено на Primary |  2.50
```

**DELETE на Primary → SELECT на Replica:**

```
DELETE FROM services WHERE name = 'Тест репликации';   -- DELETE 1

Replica:
SELECT count(*) FROM services WHERE name = 'Тест репликации';   -- 0
```

**Подтверждение подключённой реплики** в момент проверки — позиции журнала на обоих узлах
совпадают:

```
Primary:  pg_current_wal_lsn()      = 3/790007A8
Replica:  pg_last_wal_replay_lsn()  = 3/790007A8

pg_stat_replication:
  usename   | application_name | client_addr |   state   | sync_state |  sent_lsn  | replay_lsn |   replay_lag
------------+------------------+-------------+-----------+------------+------------+------------+----------------
 replicator | walreceiver      | 172.29.0.4  | streaming | async      | 3/790007A8 | 3/790007A8 | 00:00:00.00057
```

То же проверено на данных сервиса: брони, созданные через API на Primary (часть 5),
появились на Replica, а после `DELETE /api/bookings/{id}` исчезли и там — на реплике снова
ровно 300 004 брони.

---

## Часть 4. Read-only поведение Replica

Попытки записи на Replica:

```
INSERT INTO services (name, description, price) VALUES ('Запись на реплике', '', 1);
ERROR:  cannot execute INSERT in a read-only transaction

UPDATE services SET price = 99 WHERE name = 'Тест репликации';
ERROR:  cannot execute UPDATE in a read-only transaction

DELETE FROM services WHERE name = 'Тест репликации';
ERROR:  cannot execute DELETE in a read-only transaction

CREATE TABLE lab4_test (id int);
ERROR:  cannot execute CREATE TABLE in a read-only transaction

SET transaction_read_only = off;
ERROR:  cannot set transaction read-write mode during recovery
```

Причина видна в настройках:

```
 in_recovery | transaction_read_only | hot_standby
-------------+-----------------------+-------------
 t           | on                    | on
```

Сервер находится в режиме восстановления (`pg_is_in_recovery() = t`): он непрерывно
воспроизводит чужой WAL, и режим read-only снять нельзя даже явно.

Та же попытка через подключение `replica` в Django даёт тот же ответ сервера:

```
Django/replica -> cannot execute INSERT in a read-only transaction
```

### Почему Replica не может быть независимой базой для записи

1. **Поток изменений односторонний.** WAL идёт только Primary → Replica. Если бы реплика
   приняла запись, у Primary не было бы способа о ней узнать, а следующая запись WAL
   с Primary изменила бы те же блоки данных и уничтожила бы её. Две базы разошлись бы
   молча и необратимо — split-brain.
2. **Реплика — это копия состояния, а не отдельная база.** Её единственный контракт: быть
   равной Primary на момент воспроизведённого LSN. Любая собственная запись нарушает его.
3. **Отставание.** Реплика может не видеть последние транзакции Primary (часть 6). Решение
   о записи, принятое по устаревшим данным, было бы неверным — например, бронь на уже
   занятую комнату.
4. **Единая точка упорядочивания.** Первичные ключи, проверки уникальности, блокировки
   строк работают, только когда все записи проходят через один узел.

Поэтому в приложении запись жёстко привязана к Primary: функция `execute()` в
[main/repositories/base.py:47](main/repositories/base.py#L47) не принимает параметр
подключения и всегда использует `connections['default']`. Вторая линия защиты — само
подключение `replica` открывается с `default_transaction_read_only=on`
([booking_service/settings.py:76](booking_service/settings.py#L76)): даже если в конфигурации
`replica` будет указывать на Primary, запись через него сервер отклонит.

---

## Часть 5. Чтение сервиса через Replica

### Выбранный сценарий

**`GET /api/bookings`** — список бронирований с фильтрами, сортировкой и пагинацией — и два
производных списка: `GET /api/guests/{id}/bookings`, `GET /api/rooms/{id}/bookings`. Это
самый частый и тяжёлый read-сценарий API (два запроса на вызов: страница + `COUNT(*)` для
`total`), и для него допустимо, что список отстаёт от Primary на доли секунды.

Что идёт куда:

| Операция | Подключение | Узел |
|---|---|---|
| `GET /api/bookings`, списки по гостю и комнате | `replica` | Replica |
| `GET /api/bookings/{id}` — карточка брони | `default` | Primary |
| `POST`, `PUT`, `DELETE /api/bookings…` и любая другая запись | `default` | Primary |
| проверка занятости комнаты при создании брони | `default` | Primary |
| все остальные endpoint'ы | `default` | Primary |

Карточка брони и проверка занятости комнаты сознательно оставлены на Primary: они
участвуют в сценарии «создал бронь → сразу открыл её», где отставание недопустимо.

### Конфигурация и код

**Второе подключение** — [booking_service/settings.py:70-78](booking_service/settings.py#L70-L78):

```python
DATABASES['replica'] = {
    **DATABASES['default'],
    'HOST': os.getenv('POSTGRES_REPLICA_HOST') or DATABASES['default']['HOST'],
    'PORT': os.getenv('POSTGRES_REPLICA_PORT') or DATABASES['default']['PORT'],
    'OPTIONS': {
        'application_name': 'booking-backend-replica',
        'options': '-c default_transaction_read_only=on',
    },
}
```

Если `POSTGRES_REPLICA_HOST` не задан, `replica` указывает на Primary — сервис работает и
без реплики, а запись через это подключение всё равно невозможна. `application_name` виден
в `pg_stat_activity` и в логах сервера — по нему ниже доказывается маршрутизация.

**Слой доступа** — [main/repositories/base.py](main/repositories/base.py): функции чтения
получили параметр `using` со значением по умолчанию `PRIMARY`; `execute()` параметра
не имеет и пишет только в Primary.

```python
PRIMARY = 'default'
REPLICA = 'replica'

def query_all(sql, params=None, using=PRIMARY):
    with connections[using].cursor() as cursor: ...

def execute(sql, params=None):
    with connections[PRIMARY].cursor() as cursor: ...   # запись — всегда Primary
```

**Выбранный SELECT** — [main/repositories/booking_repository.py:95-116](main/repositories/booking_repository.py#L95-L116):

```python
def list_bookings(params, limit, offset, sort=None):
    ...
    return query_all(sql, values + [limit, offset], using=REPLICA)

def count_bookings(params):
    ...
    return scalar(sql, values, using=REPLICA) or 0
```

**Окружение backend** — [docker-compose.yml:172](docker-compose.yml#L172):
`POSTGRES_REPLICA_HOST: postgres-replica`.

### Доказательство: логи обоих серверов

Реплика запущена с `log_min_duration_statement=0` — она логирует каждый запрос вместе с
`application_name`. На Primary такое логирование включалось на время демонстрации
(`ALTER SYSTEM SET log_min_duration_statement = 0` + `pg_reload_conf()`) и затем сброшено.

**`GET /api/bookings?page_size=3`** — оба запроса списка пришли на Replica от подключения
`booking-backend-replica`:

```
booking_postgres_replica:
2026-09-13 21:50:40.935 app=booking-backend-replica db=booking_service LOG: duration: 5.725 ms statement:
    SELECT b.id_booking,
           b.check_in, ...
2026-09-13 21:50:40.978 app=booking-backend-replica db=booking_service LOG: duration: 41.708 ms statement:
    SELECT COUNT(*)
    FROM bookings b
    JOIN guests g ON g.id_guest = b.id_guest ...
```

На Primary за это время запросов списка нет; за всё время демонстрации на Primary
**0 запросов** от подключения `booking-backend-replica`.

**`POST /api/bookings`** — запись пришла на Primary от подключения `booking-backend`:

```
POST → {"id_booking": 300005, "id_guest": 1, "id_room": 1, "check_in": "2027-06-01",
        "check_out": "2027-06-03", "status": "confirmed", "total_price": "8400.00"}

booking_postgres:
2026-09-13 21:50:43.125 app=booking-backend db=booking_service LOG: duration: 1.704 ms statement:
    INSERT INTO bookings (id_guest, id_room, check_in, check_out, total_price, status, ...
```

На Replica этого INSERT нет — она получает изменение через WAL, а не как SQL от приложения.

**`GET /api/bookings/300005`** — карточка читается с Primary:

```
booking_postgres:
2026-09-13 21:50:45.307 app=booking-backend db=booking_service LOG: duration: 3.872 ms statement:
    ... WHERE b.id_booking = 300005
```

**Замыкание цикла:** `GET /api/bookings?guest_id=1&sort=-id` (Replica) через секунду после
POST уже содержит бронь 300005 — изменение с Primary дошло до реплики и отдано клиенту
через read-подключение.

### Цена решения

Клиент, который создал бронь и сразу запросил список, может её не увидеть — список читается
с узла, который ещё не воспроизвёл его запись. Это не ошибка, а свойство асинхронной
репликации; в части 6 оно измерено. Для сценариев, где «прочитать своё изменение» обязательно,
чтение должно идти с Primary — так и сделано для карточки брони.

---

## Часть 6. Replication lag

Инструмент — [main/management/commands/replication_status.py](main/management/commands/replication_status.py):
показывает состояние обоих подключений, `pg_stat_replication`, позиции LSN на реплике,
а с флагом `--probe N` выполняет N циклов «INSERT на Primary → сразу SELECT той же строки
на Replica» и измеряет, через сколько строка становится видна.

### 6.1. Естественное отставание: 175 из 200

```
python manage.py replication_status --probe 200
```

```
Проба: 200 циклов INSERT на Primary → SELECT на Replica
  id=3: первый SELECT не увидел строку, появилась через 0.55 мс (попыток: 2)
  id=6: первый SELECT не увидел строку, появилась через 0.43 мс (попыток: 2)
  id=8: первый SELECT не увидел строку, появилась через 0.50 мс (попыток: 2)
  ...
Видно сразу первым SELECT: 25 из 200
Первый SELECT увидел старые данные: 175 из 200
Задержка появления: min 0.26 мс, avg 0.34 мс, max 0.55 мс
```

**Момент, когда Primary уже содержит новое значение, а Replica ещё нет, пойман в 175 случаях
из 200.** Отставание — доли миллисекунды, потому что оба контейнера на одной машине, но оно
есть всегда: между COMMIT на Primary и видимостью на Replica лежат отправка WAL по сети,
запись его на диск реплики и воспроизведение.

Побочное наблюдение из той же пробы: при первом запуске команда создала таблицу на Primary
и сразу обратилась к ней на Replica — и получила
`relation "lab4.replication_probe" does not exist`. **DDL тоже едет через WAL** и тоже
запаздывает. Команда теперь дожидается появления таблицы на реплике перед пробой.

### 6.2. Отставание «крупным планом»: пауза воспроизведения

Чтобы разглядеть эффект глазами, воспроизведение WAL на реплике было приостановлено —
реплика продолжает **получать** WAL, но перестаёт его **применять**. Затем — сценарий
реального клиента через API.

| Шаг | Действие | Результат |
|---|---|---|
| 1 | Replica: `SELECT pg_wal_replay_pause()` | `pg_is_wal_replay_paused() = true` |
| 2 | `POST /api/bookings` → Primary | создана бронь **300006** |
| 3 | `GET /api/bookings?guest_id=1&sort=-id&page_size=3` → Replica | `[300005, 289829, 248255]`, total 11 — **брони 300006 нет** |
| 4 | `GET /api/bookings/300006` → Primary | `id_booking = 300006, status = confirmed` — **бронь есть** |
| 5 | `pg_stat_replication` на Primary | `sent_lsn 3/79054ED0`, `replay_lsn 3/79054C30` — **672 байта получены, но не воспроизведены** |
| 6 | Replica: `SELECT pg_wal_replay_resume()` | `replay_lsn` догнал `sent_lsn` |
| 7 | тот же `GET /api/bookings?guest_id=1&sort=-id&page_size=3` | `[300006, 300005, 289829]`, total 12 — **бронь появилась** |

Один и тот же клиент в один и тот же момент получает от API два разных ответа: карточка
(Primary) знает о брони, список (Replica) — нет. Именно это и есть replication lag с точки
зрения приложения. Пауза здесь лишь растягивает во времени то, что в п. 6.1 длится 0.3 мс.

### 6.3. Отставание под нагрузкой записи

На Primary одной транзакцией вставлено 3 000 000 строк (515 МБ), параллельно каждые
0.5 с снимались показатели с обоих узлов:

```
время UTC     sent_lsn     replay_lsn   лаг, МБ   replay_lag        Replica: с последней воспроизведённой транзакции
21:54:18.077  3/79065FE0   3/79065FE0   0.0       00:00:00.001167   00:00:01.179
21:54:18.750  3/80000000   3/7FFFFF98   0.0       00:00:00.083408   00:00:01.846
21:54:19.400  3/88440000   3/87FFFF60   4.3       00:00:00.171588   00:00:02.511
21:54:20.116  3/91400000   3/8FFFFFD0   20.0      00:00:00.186721   00:00:03.236
21:54:20.984  3/9B440000   3/9A0037A8   20.2      00:00:00.123883   00:00:04.108
21:54:21.673  3/A4000000   3/A37FFFC8   8.0       00:00:00.094965   00:00:04.775
>>> INSERT на Primary завершён в 21:54:21
21:54:22.345  3/A6714C80   3/A6714C80   0.0       00:00:00.073223   00:00:00.575
```

Что видно:

- Пока Primary пишет ~100 МБ WAL в секунду, реплика отстаёт на **до 20 МБ** журнала,
  `replay_lag` доходит до **0.19 с**. Через секунду после окончания записи отставание — ноль,
  на обоих узлах по 3 000 000 строк.
- Колонка «с последней воспроизведённой транзакции» растёт до **4.8 с** — это не ошибка
  измерения, а второе лицо лага: все 3 млн строк шли **одной транзакцией**, и пока её COMMIT
  не воспроизведён, реплика не показывает ни одной из них. Приложение, читающее с реплики
  в эти 4.8 секунды, видит состояние до начала загрузки — хотя `replay_lsn` всё это время
  движется.

### Вывод

Репликация не означает мгновенную синхронизацию. Между COMMIT на Primary и видимостью
изменения на Replica всегда есть задержка: в спокойном состоянии на одной машине — доли
миллисекунды (и тем не менее 175 из 200 «немедленных» чтений её поймали), под нагрузкой
записи — десятки мегабайт журнала и секунды на уровне транзакций, при остановке
воспроизведения — сколь угодно долго. Отставание измеримо (`pg_stat_replication`,
`pg_last_wal_replay_lsn()`) и должно учитываться при выборе, какие чтения можно отдать
реплике.

---

## Как воспроизвести

```bash
# 1. Primary с новыми параметрами (образ пересобирается — в нём entrypoint реплики)
docker compose up -d --build postgres

# 2. Роль репликации — на уже существующей базе один раз вручную
docker exec -it -e PGPASSWORD=booking booking_postgres psql -U booking -d booking_service \
  -c "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';"
#    (на пустом томе это делает deploy/postgres/initdb/00-replication.sh автоматически)

# 3. Replica — при первом старте сама снимет копию с Primary
docker compose up -d postgres-replica
docker logs -f booking_postgres_replica          # pg_basebackup → entering standby mode → streaming

# 4. Backend с двумя подключениями
docker compose up -d --build backend

# 5. Проверки
docker exec -e PGPASSWORD=booking booking_postgres psql -U booking -d booking_service -x \
  -c "SELECT * FROM pg_stat_replication;"
python manage.py replication_status --probe 200  # POSTGRES_HOST=localhost POSTGRES_PORT=5433
                                                 # POSTGRES_REPLICA_HOST=localhost POSTGRES_REPLICA_PORT=5434
docker logs -f booking_postgres_replica | grep booking-backend-replica   # запросы списка приходят сюда
```

Пересоздание реплики с нуля: `docker compose rm -sf postgres-replica && docker volume rm
booking_service_postgres_replica_data && docker compose up -d postgres-replica`. Entrypoint
сам удалит неактивный старый слот и снимет новую копию.

## Файлы

| Путь | Роль |
|---|---|
| [docker-compose.yml](docker-compose.yml) | сервисы `postgres` (Primary) и `postgres-replica`, параметры репликации, подключение backend к обоим узлам |
| [deploy/postgres/replica-entrypoint.sh](deploy/postgres/replica-entrypoint.sh) | первый запуск реплики: `pg_basebackup` с созданием слота и `standby.signal` |
| [deploy/postgres/pg_hba.conf](deploy/postgres/pg_hba.conf) | правила доступа, в том числе для replication-подключений |
| [deploy/postgres/initdb/00-replication.sh](deploy/postgres/initdb/00-replication.sh) | роль `replicator` на пустом томе |
| [deploy/postgres/Dockerfile](deploy/postgres/Dockerfile) | образ обоих узлов, копирует entrypoint реплики |
| [booking_service/settings.py](booking_service/settings.py#L52) | подключения `default` (Primary) и `replica` |
| [main/repositories/base.py](main/repositories/base.py) | параметр `using` у функций чтения; `execute()` — только Primary |
| [main/repositories/booking_repository.py](main/repositories/booking_repository.py#L91) | список бронирований читается с Replica |
| [main/management/commands/replication_status.py](main/management/commands/replication_status.py) | состояние репликации и измерение лага |

Служебную таблицу `lab4.replication_probe` команда `replication_status` создаёт при первом
запуске пробы; таблица остаётся в базе, каждая проба добавляет в неё строки.

---

## Контрольные вопросы

**1. Чем Primary отличается от Replica?** Primary — единственный экземпляр, который принимает
изменения данных и порождает WAL. Replica находится в режиме восстановления
(`pg_is_in_recovery() = t`): она непрерывно воспроизводит WAL Primary и отвечает только на
чтение. Физически это две копии одних данных; логически — источник истины и его отражение
с задержкой.

**2. Почему запись выполняем на Primary?** Потому что поток изменений односторонний:
Primary → WAL → Replica. Запись на реплику отклоняется сервером (`cannot execute INSERT
in a read-only transaction`), а если бы принималась — Primary не узнал бы о ней, следующий
WAL перезаписал бы те же блоки, и копии разошлись бы необратимо. Единый узел записи также
обеспечивает уникальность ключей, блокировки и порядок транзакций.

**3. Как изменение из Primary попадает на Replica?** Транзакция на Primary записывает
изменения блоков в WAL и фиксируется; процесс `walsender` отправляет новые записи журнала
по сети процессу `walreceiver` на реплике; тот сохраняет их в свой `pg_wal`; startup-процесс
реплики применяет записи к файлам данных. После этого SELECT на реплике видит изменение.
Реплика не получает и не выполняет SQL приложения — только журнал.

**4. Что такое WAL в контексте репликации?** Write-Ahead Log — журнал предзаписи: любое
изменение сначала пишется в него и только потом в файлы данных; так PostgreSQL
восстанавливается после сбоя. Репликация использует тот же журнал как транспорт: реплика —
это сервер, который «восстанавливается» из чужого WAL бесконечно, по мере его поступления.
`wal_level = replica` гарантирует, что в журнале есть всё, что нужно для этого.

**5. Что такое replication lag?** Отставание реплики от Primary: разница между тем, что
Primary уже зафиксировал, и тем, что реплика уже воспроизвела. Измеряется в байтах журнала
(`sent_lsn − replay_lsn`), во времени (`replay_lag` в `pg_stat_replication`) и в транзакциях
(`pg_last_xact_replay_timestamp()`). В этой работе: 0.26–0.55 мс в покое, до 20 МБ и 0.19 с
под нагрузкой, 4.8 с на уровне транзакций при одной большой загрузке.

**6. Почему следующий SELECT после INSERT может увидеть старые данные, если его отправить
на Replica?** Потому что INSERT фиксируется на Primary, не дожидаясь реплики
(`sync_state = async`), а SELECT приходит на реплику раньше, чем до неё доехал и воспроизвёлся
соответствующий WAL. Измерено: 175 из 200 таких SELECT увидели старое состояние; в части 6.2
клиент получил карточку брони с Primary и список без неё с Replica в один момент времени.

**7. Что именно масштабируется при Read Scaling?** Пропускная способность по чтению —
способность обслуживать больше одновременных читающих запросов, распределив их по нескольким
узлам. Скорость одного SQL-запроса не меняется: на реплике он выполняется тем же планом по
тем же данным. Запрос списка броней на реплике занял 5.7 мс — как и на Primary.

**8. Почему наличие Replica не отменяет необходимость индексов и оптимизации SQL?**
Реплика — точная копия, включая планы выполнения: медленный запрос остаётся медленным на
каждом узле, просто теперь их два. Добавив реплику, мы умножаем мощность на константу, а
плохой план деградирует с ростом данных линейно (лаба 2). Кроме того, реплика воспроизводит
весь WAL Primary, то есть несёт всю нагрузку записи и плюс своё чтение; чем тяжелее запросы,
тем сильнее они мешают воспроизведению и тем больше лаг.

**9. Расскажите про CAP-теорему.** В распределённой системе с репликами нельзя одновременно
гарантировать все три свойства: **Consistency** — каждое чтение возвращает результат
последней записи; **Availability** — каждый запрос получает ответ; **Partition tolerance** —
система работает при потере связи между узлами. Сетевые разрывы неизбежны, поэтому реальный
выбор — между C и A на время разрыва. Наша конфигурация: асинхронная репликация, чтение
списка с реплики — это выбор в сторону доступности: реплика ответит всегда, но может отдать
устаревшие данные (eventual consistency, части 6.1–6.2). Чтение карточки и все записи идут
на Primary — это согласованность для тех операций, где она нужна. Синхронная репликация
(`synchronous_commit = on` для реплики) сместила бы систему к C: COMMIT ждал бы подтверждения
реплики, и при её недоступности запись остановилась бы — потеря A. Уточнение PACELC: и без
разрывов сети система выбирает между задержкой (Latency) и согласованностью — асинхронная
реплика даёт быстрый COMMIT ценой лага.
