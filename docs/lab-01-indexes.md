# Лабораторная работа №1
# Индексы и EXPLAIN ANALYZE

## Часть 1. Работа с тестовой базой

Таблица `orders` заполнена 1 000 000 строк, после загрузки выполнен `ANALYZE orders`.

### Задание 3. EXPLAIN

**1. Какой план выбрал PostgreSQL?** `Gather` (Workers Planned: 2) → `Parallel Seq Scan on orders`, то есть параллельный полный перебор.

**2. Тип сканирования?** `Parallel Seq Scan`. Индекса по `user_id` нет, выбирать не из чего.

**3. Как ищутся строки?** Читается вся таблица, к каждой строке применяется `Filter: (user_id = 123)`. Оценка — 11 строк, cost до 17037.43.

### Задание 4. EXPLAIN ANALYZE

Из плана: `Parallel Seq Scan`, Planning Time 0.298 мс, Execution Time 22.755 мс, actual rows = 8, `Rows Removed by Filter: 333331`.

**1.** EXPLAIN только показывает план, запрос не выполняется. EXPLAIN ANALYZE выполняет запрос и добавляет `actual time`, реальные строки и `loops`.

**2.** Запрос выполняется целиком плюс накладные расходы на замер времени по каждому узлу.

**3.** Estimated — прогноз по статистике, actual — факт. Ожидалось 11 строк, получилось 8 (на скане 5 против 3 на воркер). Расхождение небольшое, данные генерировались случайно.

### Задание 5. Sequential Scan

**1.** В обоих запросах — `Seq Scan on orders`, без параллелизма.

**2.** Оба возвращают почти всю таблицу: первый — все 1 000 000 строк, второй — 999 999, фильтр `amount > 0` отсёк одну строку (`Rows Removed by Filter: 1`). Индекс тут только добавил бы лишний уровень.

**3.** Нет, Seq Scan плох только когда нужна маленькая часть данных, а читается всё.

**Вывод.** Seq Scan выгоднее индекса, когда выбирается большая доля таблицы — чтение подряд дешевле случайных переходов «индекс → таблица».

### Задание 6. Первый индекс

```sql
CREATE INDEX idx_orders_user_id ON orders(user_id);
ANALYZE orders;
```

| Метрика | До индекса | После индекса |
|---|---|---|
| Тип Scan | Parallel Seq Scan (+ Gather) | Bitmap Heap Scan + Bitmap Index Scan |
| Execution Time | 22.755 мс | 0.225 мс |
| Обработано строк | ~1 000 000 просмотрено (333331 отброшено на воркера), найдено 8 | 8 строк, 8 блоков (`Heap Blocks: exact=8`) |
| Индекс | нет | `idx_orders_user_id` |

**1.** План изменился полностью, параллельный перебор заменён индексным доступом.
**2.** Да, `Bitmap Index Scan on idx_orders_user_id`, `Index Cond: (user_id = 123)`.
**3.** Ускорение примерно в 100 раз.

### Задание 7. Индекс и низкая селективность

```sql
CREATE INDEX idx_orders_status ON orders(status);
```

**1.** Не всегда — наличие индекса не гарантирует его выбор.

**2.** Статусов четыре, каждый занимает ~25% таблицы (`PAID` — 249584 строки, `NEW` — 250322). При такой доле точечный доступ невыгоден; здесь ещё оправдан Bitmap Scan, но при большей доле планировщик уйдёт в Seq Scan, как с `amount > 0`.

**3.** Это главный критерий: мало строк → Index Scan, средняя доля → Bitmap Scan, большая → Seq Scan.

### Задание 8. Селективность

| Статус | Строк | % таблицы | Индекс | Тип Scan | Execution Time |
|---|---|---|---|---|---|
| NEW | 250322 | ~25.0% | да | Bitmap Heap + Index Scan | 44.7 мс |
| PAID | 249584 | ~25.0% | да | Bitmap Heap + Index Scan | 43.1 мс |
| DELIVERED | 250704 | ~25.1% | да | Bitmap Heap + Index Scan | 43.9 мс |
| CANCELLED | 249390 | ~24.9% | да | Bitmap Heap + Index Scan | 42.5 мс |

Планы и время одинаковые — статусы распределены равномерно.

**Вывод.** Чем меньше доля подходящих строк, тем выгоднее индекс. В задании 6 условие отбирало 8 строк из миллиона и дало ускорение в 100 раз; здесь при 25% выигрыш сводится только к замене Seq Scan на Bitmap Scan.

### Задание 9. Индекс для диапазонного запроса

```sql
CREATE INDEX idx_orders_created_at ON orders(created_at);
```

| Диапазон | Строк | % таблицы | Индекс | Тип Scan | Execution Time |
|---|---|---|---|---|---|
| 7 дней (до индекса) | 8080 | ~0.8% | нет | Parallel Seq Scan | 35.7 мс |
| 7 дней (после) | 8078 | ~0.8% | да | Bitmap Heap Scan | 12.2 мс |
| 1 месяц | 41656 | ~4.2% | да | Bitmap Heap Scan | 20.0 мс |
| 1 год | 499869 | ~50% | нет | Seq Scan | 117.8 мс |

**1.** Нет. На диапазоне в год индекс не используется, идёт Seq Scan с фильтром (отброшено 500131 строка).
**2.** Чем шире диапазон, тем больше строк подходит и тем менее выгоден индекс.
**3.** Примерно с 50% таблицы индекс перестаёт окупаться.

### Задание 10. Bitmap Scan

Запрос `WHERE status = 'NEW'` дал нужный план: 250322 строки за 54.584 мс.

**1.** `Bitmap Index Scan` идёт по индексу и строит битовую карту блоков, где лежат подходящие строки.

**2.** `Bitmap Heap Scan` читает эти блоки по карте в порядке номеров (`Heap Blocks: exact=10828`) и перепроверяет условие через `Recheck Cond`.

**3.** Строк много и они разбросаны по таблице. Обычный Index Scan дал бы 250 тысяч случайных обращений к диску, а Bitmap читает блоки почти последовательно. Это компромисс между Index Scan и Seq Scan.

### Задание 11. Использование нескольких индексов

План: `Bitmap Heap Scan` → `Bitmap Index Scan on idx_orders_user_id`, условие по статусу — через `Filter` (`Rows Removed by Filter: 5`), осталось 3 строки.

**1.** Один — `idx_orders_user_id`.
**2.** `BitmapAnd` в плане нет.
**3.** PostgreSQL может взять карты обоих индексов и пересечь их через `BitmapAnd` (или объединить через `BitmapOr`), если оба условия селективны. Здесь `user_id = 123` даёт 8 строк — сужать нечего, дешевле отфильтровать статус после чтения.

### Задание 12. Составной индекс

```sql
CREATE INDEX idx_orders_user_status ON orders(user_id, status);
```

| Вариант | План | Execution Time |
|---|---|---|
| Индекс по `user_id` + Filter | Bitmap Heap Scan + Filter | 0.110 мс |
| Составной `(user_id, status)` | Index Scan, оба условия в `Index Cond` | 0.172 мс |

**1.** По времени составной даже чуть проиграл, но на выборке из трёх строк это шум. Структурно он лучше — нет отдельного `Filter`.

**2.** Нет. Он больше весит, медленнее обновляется и бесполезен для запросов только по второй колонке.

**3.** От того, как пишутся запросы: колонки идут вместе в `WHERE` — составной индекс, независимо — два отдельных. Плюс нагрузка на запись.

### Задание 13. Влияние порядка колонок

С индексом `idx_orders_user_created_at` на `(user_id, created_at)`:

| Запрос | Индекс | Строк | Время |
|---|---|---|---|
| `user_id = 123` | `idx_orders_user_created_at`, Bitmap Heap Scan | 8 | 0.078 мс |
| `user_id = 123 AND created_at > 30д` | тот же, Index Scan, оба условия в Index Cond | 0 | 0.212 мс |
| `created_at > 30д` | не подошёл, взят `idx_orders_created_at` | 40305 | 20.662 мс |

После создания `idx_orders_created_at_user` на `(created_at, user_id)`:

| Запрос | Индекс | Строк | Время |
|---|---|---|---|
| `user_id = 123` | по-прежнему `idx_orders_user_created_at` | 8 | 0.106 мс |
| `created_at > 30д` | индекс с `created_at` ведущей колонкой | 40304 | 22.403 мс |

**1.** Индекс отсортирован сначала по первой колонке, внутри неё — по второй, поэтому применим только при фильтрации по ведущей колонке или по обеим.

**2.** Это физически разные B-tree с разным порядком ключей, заменить одно другим нельзя.

**3.** Запросы 1 и 2 — `(user_id, created_at)`, запрос 3 — индекс, где `created_at` первый.

### Задание 14. Индекс и сортировка

```sql
CREATE INDEX idx_orders_user_created_at_desc ON orders(user_id, created_at DESC);
```

**1.** Нет, `Sort (Sort Key: created_at DESC, quicksort)` остался и после создания индекса. Bitmap Index Scan переключился на новый индекс, но сортировка не ушла.

**2.** B-tree хранит значения упорядоченно, и при обычном `Index Scan` строки отдаются сразу в нужном порядке.

**3.** Индекс заточен под «равенство по user_id + сортировка по created_at DESC», но строк всего 8, планировщик выбрал Bitmap-путь, а он читает блоки по номерам и порядок теряет. На большем объёме тот же индекс дал бы Index Scan без Sort.

### Задание 15. Pagination Query

**До:** `Bitmap Heap Scan` + отдельный узел `Sort`.

**Индекс:**
```sql
CREATE INDEX idx_orders_user_created_at_desc ON orders(user_id, created_at DESC);
```

**После:** `Limit → Sort (quicksort, 26kB) → Bitmap Heap Scan (Heap Blocks: exact=8) → Bitmap Index Scan on idx_orders_user_created_at_desc`. Execution Time 0.162 мс.

**Сравнение.** План почти не изменился, `Sort` сохранился, время сопоставимо — у пользователя всего 8 заказов, поэтому выбран Bitmap Scan.

**Структура индекса.** `user_id` первым — условие равенства, определяет читаемый поддиапазон. `created_at DESC` вторым — направление совпадает с `ORDER BY`, чтобы при `LIMIT` чтение останавливалось после 20 строк без сортировки всей выборки. На малом объёме эффект не проявился.

### Задание 16. Index Only Scan

С существующим индексом получился `Bitmap Heap Scan`: в индексе нет колонки `id`, которая есть в `SELECT`. Создаём покрывающий индекс:

```sql
CREATE INDEX idx_orders_user_id_id ON orders(user_id, id);
```

Результат: `Index Only Scan using idx_orders_user_id_id`, `Heap Fetches: 0`, Execution Time 0.116 мс.

**1.** Index Scan идёт в таблицу за данными, Index Only Scan берёт всё из индекса.
**2.** Все запрошенные колонки (`id`, `user_id`) есть в индексе — это подтверждает `Heap Fetches: 0`.
**3.** Условия: все колонки SELECT и WHERE в индексе; актуальная visibility map (обновляет VACUUM); план дешевле альтернатив.

**Дополнительно — INCLUDE:**
```sql
CREATE INDEX idx_orders_user_id_include ON orders(user_id) INCLUDE (id, status, created_at);
```
INCLUDE-колонки лежат только в листовых страницах, в поиске не участвуют, но доступны для чтения — можно получить Index Only Scan для более широкого SELECT, не раздувая ключ.

### Задание 17. Частичный индекс

```sql
CREATE INDEX idx_orders_new ON orders(created_at) WHERE status = 'NEW';
```

План не изменился: `Sort (external merge, Disk: 16208kB)` поверх `Bitmap Heap Scan` через `idx_orders_status`, ~95 мс. Частичный индекс не выбран, потому что `NEW` занимает те же ~25% таблицы (250322 строки), а не малую долю.

**1.** Строится только по подмножеству строк — меньше весит, дешевле обновляется.
**2.** Когда значение действительно редкое, единицы процентов таблицы.
**3.** Он привязан к своему условию в `WHERE` и работает только для запросов с тем же условием.

### Задание 18. Индекс по выражению

**До:** `Seq Scan on users`, `Filter: (lower(email) = 'test@example.com')`, 0.049 мс. Индекс `idx_users_email` не используется.

**Почему?** Он построен на исходных значениях `email`, а запрос ищет результат `LOWER(email)`. Это разные ключи, вычислять функцию для каждого значения индекса PostgreSQL не будет.

```sql
CREATE INDEX idx_users_lower_email ON users(LOWER(email));
```

**После:** `Index Scan using idx_users_lower_email`, `Index Cond: (lower(email) = ...)`, 0.051 мс.

**Вывод.** Индекс должен быть построен ровно на том выражении, что используется в запросе — тогда в нём хранятся уже вычисленные значения.

### Задание 19. Влияние индексов на INSERT

Вставка 500 000 строк в две одинаковые таблицы:

| Таблица | Индексы | Execution Time |
|---|---|---|
| `orders_test1` | только PK | 820.034 мс |
| `orders_test2` | PK + 4 индекса | 3232.893 мс |

**1.** Время выросло примерно в 4 раза.
**2.** При вставке строки обновляется не только heap, но и каждый индекс.
**3.** Для каждого индекса вычисляется ключ и вставляется в B-tree, при необходимости с разделением страниц. При 4 индексах это 5 операций записи вместо одной.

### Задание 20. Неиспользуемые индексы

**1.** Чаще всего — `idx_orders_status` (15) и `bookings_pkey` (15), далее `rooms_pkey`, `employees_pkey` (13), `services_pkey` (11), `idx_orders_created_at` (8).

**2.** Да, у большинства `idx_scan = 0`: индексы `payments`, `roomcleanings`, `bookingservices`, все UNIQUE и `_like` индексы `guests`, а также `orders_pkey`, `idx_orders_created_at_user`, `idx_orders_new`, `users_pkey`, `idx_users_email`.

**3.** Нет. `idx_scan = 0` значит только то, что индекс не использовался с момента сброса статистики. `orders_pkey` тоже показывает ноль, хотя PK нужен для целостности и работает при UPDATE/DELETE по id — мы их просто не тестировали.

**4.** Риски: замедление редких, но важных запросов; поломка ограничений при удалении PK/UNIQUE; блокировки и медленные каскады при удалении индексов под FK; решение по неполной статистике.

### Задание 21. Оптимизация запроса

**План до:**
```
Limit → Index Scan using idx_orders_user_created_at_desc on orders
  Index Cond: ((user_id = 123) AND (created_at >= now() - '30 days'))
  Filter: ((status)::text = 'PAID'::text)
```
Execution Time: 0.047 мс.

**Проблема.** Условие по `status` не в индексе и отрабатывает через `Filter` — строки читаются, а потом отбрасываются.

**Индекс:**
```sql
CREATE INDEX idx_orders_user_status_created_at ON orders (user_id, status, created_at DESC);
```

**Порядок колонок.** `user_id` и `status` — равенства, идут первыми и фиксируют узкий поддиапазон. `created_at DESC` — диапазон и ключ сортировки, ставится последним, направление совпадает с `ORDER BY`. Правило: равенства вперёд, диапазон и сортировку в конец.

**План после:**
```
Limit → Index Scan using idx_orders_user_status_created_at on orders
  Index Cond: ((user_id = 123) AND (status = 'PAID') AND (created_at >= now() - '30 days'))
```
Execution Time: 0.088 мс.

**Сравнение.** Все три условия перешли из `Filter` в `Index Cond`, `Sort` нет в обоих планах. По времени новый вариант формально медленнее, но запрос вернул 0 строк и такие величины скачут от прогона к прогону. Выигрыш проявится при росте данных, когда не придётся читать записи, которые сразу выбрасываются.

---

## Часть 2. Работа со своим сервисом

REST API системы бронирования отеля (Django + PostgreSQL 16, SQL через слой репозиториев). Данные: `bookings` — 300 004 строки, `payments` — 150 004, `bookingservices` — 98 014, `guests` — 50 004, `rooms` — 305.

### Задание 22. Scaling Entity

**Таблица:** `bookings`.

**За что отвечает.** Одна строка — один факт бронирования номера гостем на интервал дат: `id_guest`, `id_room`, `check_in`/`check_out`, `total_price`, `status` (`pending`, `confirmed`, `checked_in`, `checked_out`, `cancelled`), `created_at`/`updated_at`. На неё завязаны `payments` и `bookingservices`.

**Почему растёт быстрее остальных.** Остальные таблицы — справочники с ограниченным ростом (`rooms`, `roomtypes`, `services`) или насыщающиеся (`guests` — постоянные гости переиспользуют запись). `bookings` — поток событий: строки только добавляются, отменённые брони не удаляются, а получают `status = 'cancelled'` (~20% данных). `payments` и `bookingservices` растут производно, ~0.5 и ~0.3 записи на бронь.

**Объём через год.** 300 комнат, загрузка ~70%, средняя длительность 3.5 ночи: `300 × 365 × 0.7 / 3.5 ≈ 22 000` заездов в год плюс ~20% отмен ≈ 27 тыс. строк на объект. При 5–6 объектах — ~150 тыс. строк в год. Прогноз: через год ≈450 тыс., через три года ≈1 млн.

**Поля для фильтрации** (из `booking_repository._filters`): `status` (равенство), `created_at` (сортировка по умолчанию DESC + диапазон), `id_guest`, `id_room` (равенство), `check_in` (диапазон), `check_in` + `check_out` (пересечение интервалов), `id_booking` (PK).

### Задание 23. Выбранные запросы

Запросы взяты из слоя репозиториев (`main/repositories/booking_repository.py`), который выполняет
весь SQL сервиса. Ниже — та же форма запроса, что уходит в БД, с подставленными значениями
(в коде они передаются параметрами `%s`).

**Query 1 — поиск по конкретному идентификатору.**
`GET /api/guests/{guest_id}/bookings`, функция `list_bookings()` с фильтром `guest_id`.

```sql
SELECT b.id_booking, b.check_in, b.check_out, b.total_price, b.status,
       b.created_at, b.updated_at,
       g.id_guest, g.last_name AS guest_last_name, g.first_name AS guest_first_name,
       g.email AS guest_email,
       r.id_room, r.room_number, r.floor,
       rt.id_type, rt.name AS room_type, rt.price_per_night
FROM bookings b
JOIN guests g     ON g.id_guest = b.id_guest
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
WHERE b.id_guest = 29604
ORDER BY b.created_at DESC
LIMIT 20 OFFSET 0;
```

**Query 2 — запрос с несколькими условиями.**
`COUNT(*)` для поля `total` в пагинации, функция `count_bookings()`. Выполняется на каждый вызов
списка вместе с Query 3.

```sql
SELECT COUNT(*)
FROM bookings b
JOIN guests g     ON g.id_guest = b.id_guest
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
WHERE b.status = 'confirmed'
  AND b.check_in >= '2026-09-10'
  AND b.check_in <= '2026-10-10';
```

**Query 3 — фильтрация + сортировка + ограничение.**
`GET /api/bookings?status=confirmed`, функция `list_bookings()` с фильтром `status`.

```sql
SELECT b.id_booking, b.check_in, b.check_out, b.total_price, b.status,
       b.created_at, b.updated_at,
       g.id_guest, g.last_name AS guest_last_name, g.first_name AS guest_first_name,
       g.email AS guest_email,
       r.id_room, r.room_number, r.floor,
       rt.id_type, rt.name AS room_type, rt.price_per_night
FROM bookings b
JOIN guests g     ON g.id_guest = b.id_guest
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
WHERE b.status = 'confirmed'
ORDER BY b.created_at DESC
LIMIT 20 OFFSET 0;
```

**Query 4 — лента без фильтров.**
`GET /api/bookings` без параметров, тот же `list_bookings()` с пустым `WHERE`. Самый частый вызов API.

```sql
SELECT b.id_booking, b.check_in, b.check_out, b.total_price, b.status,
       b.created_at, b.updated_at,
       g.id_guest, g.last_name AS guest_last_name, g.first_name AS guest_first_name,
       g.email AS guest_email,
       r.id_room, r.room_number, r.floor,
       rt.id_type, rt.name AS room_type, rt.price_per_night
FROM bookings b
JOIN guests g     ON g.id_guest = b.id_guest
JOIN rooms r      ON r.id_room = b.id_room
JOIN roomtypes rt ON rt.id_type = r.id_type
ORDER BY b.created_at DESC
LIMIT 20 OFFSET 0;
```

### Задание 24. Базовое измерение

Замеры до добавления новых индексов. По `status`, `created_at`, `check_in` индексов не было.

| Запрос | Тип Scan по `bookings` | Execution Time | Индексы |
|---|---|---|---|
| Query 1 | Bitmap Index Scan + Bitmap Heap Scan | 0.256 мс | `bookings_id_guest_90302331`, `guests_pkey`, `roomtypes_pkey` |
| Query 2 | Parallel Seq Scan, `Rows Removed by Filter: 99613` ×3 | 7.311 мс | по `bookings` — нет |
| Query 3 | Parallel Seq Scan + Sort 60 тыс. строк, `Rows Removed by Filter: 79960` ×3 | 14.471 мс | по `bookings` — нет |
| Query 4 | Parallel Seq Scan + полный Seq Scan `guests` + top-N heapsort | 59.993 мс | нет |

В Query 2 прочитаны все 300 тыс. строк ради 1165. В Query 3 отсортированы 60 123 строки (quicksort, 2990kB на воркер) ради top-20. В Query 4 hash join соединяет 300 тыс. броней с 50 тыс. гостей, стоимость не зависит от `LIMIT`.

### Задание 25. Анализ текущих индексов

| Таблица | Индекс | Колонки | Размер | idx_scan | Кто использует |
|---|---|---|---|---|---|
| bookings | `bookings_pkey` | `id_booking` | 11 МБ | 199 020 | `GET /api/bookings/{id}`, FK из payments |
| bookings | `bookings_id_room_00b1400d` | `id_room` | 5.2 МБ | 54 | `?room_id`, проверка дат |
| bookings | `bookings_id_guest_90302331` | `id_guest` | 4.5 МБ | 45 | Query 1, `?guest_id` |
| bookingservices | `bookingservices_pkey` | `(id_booking, id_service)` | 2 МБ | 50 006 | `ON CONFLICT`, удаление позиции |
| bookingservices | `..._id_booking_...`, `..._id_service_...` | | 1.2 МБ + 336 КБ | 0 | дублирует префикс PK / нет endpoint'а |
| guests | `guests_pkey` | `id_guest` | 1.1 МБ | 307 224 | JOIN в списках |
| guests | `guests_email_key`, `_phone_key`, `_passport_number_key` + `_like` | | ~13 МБ суммарно | 0 | UNIQUE-контроль при вставке |
| payments | `payments_pkey` | `id_payment` | 3.3 МБ | 5 | `GET /api/payments/{id}` |
| payments | `payments_id_booking_...` | `id_booking` | 4.3 МБ | 0 | платежи брони |
| rooms | `rooms_pkey` | `id_room` | 16 КБ | 100 183 | JOIN в списках |

Высокие `idx_scan` у PK накручены генератором данных. Индексы `guests` с нулевым использованием занимают ~13 МБ. Главное: по `status`, `created_at`, `check_in` в `bookings` индексов нет — это и есть корень проблем Query 2, 3, 4.

### Задание 26. Найденные проблемы

**Query 1.** Проблем нет, 0.256 мс. По `bookings` Bitmap Index Scan, Seq Scan только по `rooms` (305 строк). Селективность 19 из 300 004 = 0.006%, индекс `bookings_id_guest_90302331` уже есть. Составной `(id_guest, created_at)` убрал бы `Sort`, но сортируются 19 строк — не стоит 5 МБ и замедления вставки. Отклонено.

**Query 2.** Проблема есть: 7.3 мс на каждый вызов списка. `Parallel Seq Scan`, прочитано 300 тыс. строк ради 1165. `status = 'confirmed'` сам по себе даёт 20% таблицы (60 123 строки), но связка со `check_in` — 0.39%. Нужен составной `(status, check_in)`. Дополнительно: JOIN'ы внутри `COUNT(*)` — INNER JOIN по обязательным FK, они не меняют число строк и могут быть убраны.

**Query 3.** 14.5 мс ради 20 строк. Условие даёт 20% таблицы, но реальная селективность задаётся `LIMIT`: 20 из 300 004 = 0.007%. Нужен `(status, created_at DESC)` — даст и фильтр, и готовый порядок. Отдельно: `OFFSET`-пагинация деградирует на глубоких страницах, правильнее keyset-пагинация, но это меняет контракт API.

**Query 4.** Худший результат, 60 мс. Seq Scan по `bookings` и `guests` сразу. Селективность снова в `LIMIT` — 0.007%. Нужен `(created_at DESC)`, тогда JOIN'ы выполнятся для 20 строк.

**Дополнительно.** `find_overlapping()` (проверка занятости номера при каждом создании брони): `Bitmap Index Scan on bookings_id_room_00b1400d` отбирает 1056 строк, из них по датам подходит 1, `Rows Removed by Filter: 39`, 0.532 мс. Составной `(id_room, check_in)` сузил бы диапазон, но 0.53 мс приемлемо, а это путь записи — индекс не добавляю.

### Задание 27. Выбранные индексы

Основной запрос для полного цикла — Query 3, попутно Query 2 и Query 4.

| Индекс | Под запрос | Порядок колонок |
|---|---|---|
| `idx_bookings_created_at` на `(created_at DESC)` | Query 4 | Одна колонка, она же ключ сортировки по умолчанию; `DESC` совпадает с `ORDER BY` |
| `idx_bookings_status_created` на `(status, created_at DESC)` | Query 3 | `status` — равенство, фиксирует поддиапазон; внутри него записи уже упорядочены, `LIMIT` останавливает чтение |
| `idx_bookings_status_check_in` на `(status, check_in)` | Query 2 | Равенство впереди, диапазон сзади. Обратный порядок заставил бы читать все статусы и отбрасывать 80% |

Составной `(status, created_at DESC)` не заменяет `(created_at DESC)`: в Query 4 условия по `status` нет, а для глобального порядка пришлось бы обойти и слить все поддиапазоны статусов.

### Задание 28. Реализация

Индексы объявлены через `models.Index` в `Meta` модели `Booking` и применены миграцией `0002_booking_idx_bookings_created_at_and_more.py`:

```sql
CREATE INDEX idx_bookings_created_at      ON bookings (created_at DESC);
CREATE INDEX idx_bookings_status_created  ON bookings (status, created_at DESC);
CREATE INDEX idx_bookings_status_check_in ON bookings (status, check_in);
```

`entrypoint.sh` выполняет `migrate --noinput` при старте контейнера, поэтому изменение воспроизводимо на чистой базе.

### Задание 29. Повторное измерение

| Метрика | Query 1 | Query 2 | Query 3 | Query 4 |
|---|---|---|---|---|
| Тип Scan (до) | Bitmap Index Scan | Parallel Seq Scan | Parallel Seq Scan + Sort | Parallel Seq Scan ×2 + heapsort |
| Тип Scan (после) | Bitmap Index Scan | Bitmap Index Scan | **Index Scan** | **Index Scan** |
| Execution Time (до) | 0.256 мс | 7.311 мс | 14.471 мс | 59.993 мс |
| Execution Time (после) | 0.280 мс | 3.418 мс | **0.675 мс** | **0.576 мс** |
| Ускорение | — | 2.1× | **21.4×** | **104×** |
| Actual Rows (до) | 19 | 388 ×3, прочитано 300 004 | 20 041 ×3, прочитано 300 004 | 100 001 ×3, прочитано 300 004 |
| Actual Rows (после) | 19 | 1165 | **20** | **20** |
| Rows Removed by Filter | 0 → 0 | 99 613 ×3 → **0** | 79 960 ×3 → **0** | — |
| Sort в плане | есть → есть | — | **есть → нет** | **есть → нет** |
| Индекс (после) | `bookings_id_guest_90302331` | `idx_bookings_status_check_in` | `idx_bookings_status_created` | `idx_bookings_created_at` |

В Query 3 `Sort` исчез, `Hash Join` заменился на `Nested Loop` с `Memoize` — JOIN'ы теперь выполняются для 20 строк. На узле Index Scan `actual rows=20` при `estimated rows=60121`: `LIMIT` остановил чтение после двадцатой строки, то есть стоимость запроса наконец стала зависеть от `LIMIT`.

В Query 4 полный `Seq Scan` по `guests` (50 004 строки) заменился 20 точечными Index Scan.

В Query 2 все три условия ушли в `Index Cond`, `Rows Removed by Filter` исчез. Ускорение скромнее, потому что оставшиеся 3.4 мс — это 1165 итераций JOIN'ов, лишних в `COUNT(*)`.

Query 1 не изменился: у новых индексов ведущая колонка `status`, а фильтр идёт по `id_guest` — то же самое, что в задании 13. Разница 0.024 мс — шум.

**Вывод.** Выигрыш дало совпадение структуры индекса с формой запроса: ведущая колонка под равенство, вторая под `ORDER BY` в том же направлении. План «прочитать всё → отсортировать всё → взять 20» превратился в «прочитать 20 строк и остановиться».

### Задание 30. Почему нельзя индексировать всё?

**Размер.** У `bookings` шесть индексов: `idx_bookings_status_created` 12 МБ, `bookings_pkey` 11 МБ, `idx_bookings_created_at` 7.9 МБ, `bookings_id_room` 5.3 МБ, `bookings_id_guest` 4.5 МБ, `idx_bookings_status_check_in` 3.8 МБ. Итого heap 34 МБ против 44 МБ индексов — индексы занимают больше места, чем данные. Плюс они конкурируют за `shared_buffers`, вытесняя оттуда реальные данные.

**INSERT.** Вставка 100 000 строк: без индексов 66 мс, с 6 индексами 441 мс — замедление в 6.7 раза. Шесть индексов = семь операций записи вместо одной. То же измерено в задании 19 на `orders`: 820 мс → 3233 мс.

**UPDATE.** В PostgreSQL UPDATE — это вставка новой версии строки (MVCC). Если обновлённая колонка входит хотя бы в один индекс, записи добавляются во все индексы, а HOT-update становится невозможен. У нас `update_booking()` пишет `status`, который теперь входит в два индекса.

**DELETE.** Строка помечается мёртвой, записи в индексах остаются до `VACUUM`. Чем больше индексов, тем дольше VACUUM и тем сильнее bloat.

**Реальное использование.** Шесть индексов `guests` с `idx_scan = 0` занимают ~13 МБ. Индекс окупается, только если планировщик его выбирает: в заданиях 7 и 8 при `status = 'PAID'` (25% таблицы) PostgreSQL проигнорировал существующий индекс и пошёл в Seq Scan.

**Планирование.** `Planning Time` вырос с ~1.13 мс до ~1.83 мс после добавления трёх индексов — для запроса, выполняющегося 0.675 мс, это дороже самого выполнения.

**Итог.** Индекс — это сделка: место на диске, замедление записи, работа VACUUM и время планирования в обмен на быстрое чтение конкретных запросов. Поэтому добавлено ровно три индекса под четыре измеренных запроса, а кандидаты `(id_guest, created_at)` и `(id_room, check_in)` отклонены — выигрыш не окупает цену.