-- Таблица бронирований на шарде.
--
-- Одинаковая на всех шардах: каждый хранит свою часть броней, какую именно —
-- решает router по id_guest. Колонки совпадают с public.bookings основной базы.
--
-- Внешних ключей на guests и rooms нет: эти таблицы живут в основной базе,
-- а PostgreSQL не умеет проверять ссылки между разными серверами.
-- id_booking выдаётся централизованно (последовательностью основной базы),
-- поэтому остаётся уникальным во всей системе, а не только внутри шарда.

CREATE TABLE IF NOT EXISTS bookings (
    id_booking  BIGINT        PRIMARY KEY,
    id_guest    INTEGER       NOT NULL,
    id_room     INTEGER       NOT NULL,
    check_in    DATE          NOT NULL,
    check_out   DATE          NOT NULL,
    total_price NUMERIC(12,2) NOT NULL,
    status      VARCHAR(20)   NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL,
    updated_at  TIMESTAMPTZ   NOT NULL
);

-- Все запросы к шарду идут по ключу шардирования
CREATE INDEX IF NOT EXISTS bookings_id_guest_idx ON bookings (id_guest);
