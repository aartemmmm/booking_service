"""
Массовая генерация тестовых данных.

Данные создаются полностью на стороне PostgreSQL (INSERT ... SELECT generate_series),
поэтому миллионы строк вставляются без передачи данных через приложение.

Примеры:
    python manage.py generate_data --guests 100000 --bookings 1000000
    python manage.py generate_data --truncate --rooms 500 --guests 100000 \
        --bookings 1000000 --payments 500000 --booking-services 300000
"""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

LAST_NAMES = "(ARRAY['Иванов','Петров','Сидоров','Кузнецов','Попов','Волков','Морозов','Лебедев','Новиков','Козлов'])"
FIRST_NAMES = "(ARRAY['Алексей','Мария','Дмитрий','Ольга','Сергей','Анна','Игорь','Екатерина'])"
BOOKING_STATUSES = "(ARRAY['pending','confirmed','checked_in','checked_out','cancelled'])"
PAYMENT_METHODS = "(ARRAY['card','cash','transfer','online'])"
PAYMENT_STATUSES = "(ARRAY['pending','success','partial','failed','refunded'])"

TRUNCATE_SQL = """
TRUNCATE TABLE bookingservices, payments, roomcleanings, bookings, guests, rooms
RESTART IDENTITY CASCADE
"""

GUESTS_SQL = f"""
INSERT INTO guests (last_name, first_name, middle_name, phone, email, passport_number, created_at)
SELECT {LAST_NAMES}[1 + (i %% 10)],
       {FIRST_NAMES}[1 + (i %% 8)],
       NULL,
       '+7' || lpad((%(offset)s + i)::text, 10, '0'),
       'guest' || (%(offset)s + i) || '@example.com',
       'PASS' || lpad((%(offset)s + i)::text, 10, '0'),
       NOW() - (random() * 730) * INTERVAL '1 day'
FROM generate_series(%(start)s, %(end)s) AS s(i)
"""

ROOMS_SQL = """
WITH t AS (SELECT array_agg(id_type ORDER BY id_type) AS ids FROM roomtypes)
INSERT INTO rooms (room_number, id_type, floor, status)
SELECT 'G' || (%(offset)s + i),
       t.ids[1 + (i %% array_length(t.ids, 1))],
       1 + (i %% 20),
       'available'
FROM generate_series(%(start)s, %(end)s) AS s(i), t
"""

BOOKINGS_SQL = f"""
WITH src AS MATERIALIZED (
    SELECT 1 + floor(random() * %(guest_count)s)::bigint AS guest_rn,
           1 + floor(random() * %(room_count)s)::bigint  AS room_rn,
           NOW() - (random() * 730) * INTERVAL '1 day'   AS created_at,
           1 + floor(random() * 14)::int                 AS nights,
           floor(random() * 30)::int                     AS lead_days,
           1 + floor(random() * 5)::int                  AS status_idx
    FROM generate_series(%(start)s, %(end)s) AS s(i)
)
INSERT INTO bookings (id_guest, id_room, check_in, check_out, total_price, status,
                      created_at, updated_at)
SELECT g.id_guest,
       r.id_room,
       src.created_at::date + src.lead_days,
       src.created_at::date + src.lead_days + src.nights,
       ROUND(r.price_per_night * src.nights, 2),
       {BOOKING_STATUSES}[src.status_idx],
       src.created_at,
       src.created_at
FROM src
JOIN tmp_guest_ids g ON g.rn = src.guest_rn
JOIN tmp_room_ids r  ON r.rn = src.room_rn
"""

PAYMENTS_SQL = f"""
WITH src AS MATERIALIZED (
    SELECT 1 + floor(random() * %(booking_count)s)::bigint AS booking_rn,
           0.5 + random() * 0.5                           AS paid_share,
           1 + floor(random() * 4)::int                   AS method_idx,
           1 + floor(random() * 5)::int                   AS status_idx,
           NOW() - (random() * 730) * INTERVAL '1 day'    AS created_at
    FROM generate_series(%(start)s, %(end)s) AS s(i)
)
INSERT INTO payments (id_booking, payment_date, amount, method, status, created_at)
SELECT b.id_booking,
       b.check_in,
       ROUND((b.total_price * src.paid_share)::numeric, 2),
       {PAYMENT_METHODS}[src.method_idx],
       {PAYMENT_STATUSES}[src.status_idx],
       src.created_at
FROM src
JOIN tmp_booking_ids b ON b.rn = src.booking_rn
"""

BOOKING_SERVICES_SQL = """
WITH src AS MATERIALIZED (
    SELECT 1 + floor(random() * %(booking_count)s)::bigint AS booking_rn,
           1 + floor(random() * %(service_count)s)::bigint AS service_rn,
           1 + floor(random() * 3)::int                    AS quantity
    FROM generate_series(%(start)s, %(end)s) AS s(i)
)
INSERT INTO bookingservices (id_booking, id_service, quantity)
SELECT b.id_booking, sv.id_service, src.quantity
FROM src
JOIN tmp_booking_ids b  ON b.rn = src.booking_rn
JOIN tmp_service_ids sv ON sv.rn = src.service_rn
ON CONFLICT (id_booking, id_service) DO NOTHING
"""


class Command(BaseCommand):
    help = 'Сгенерировать большой объём тестовых данных прямо в PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--guests', type=int, default=0, help='Сколько гостей создать')
        parser.add_argument('--rooms', type=int, default=0, help='Сколько комнат создать')
        parser.add_argument('--bookings', type=int, default=0, help='Сколько бронирований создать')
        parser.add_argument('--payments', type=int, default=0, help='Сколько платежей создать')
        parser.add_argument(
            '--booking-services', type=int, default=0, help='Сколько связей бронь-услуга создать'
        )
        parser.add_argument(
            '--batch-size', type=int, default=50000, help='Размер одной пачки вставки'
        )
        parser.add_argument(
            '--truncate',
            action='store_true',
            help='Очистить bookings, payments, bookingservices, guests, rooms перед генерацией',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size < 1:
            raise CommandError('--batch-size должен быть больше 0.')

        with connection.cursor() as cursor:
            if options['truncate']:
                self.stdout.write('Очистка таблиц...')
                cursor.execute(TRUNCATE_SQL)

            if options['rooms']:
                if not self._count(cursor, 'roomtypes'):
                    raise CommandError('Нет типов комнат. Сначала запустите manage.py seed_demo.')
                offset = self._max_id(cursor, 'rooms', 'id_room')
                self._insert_batches(
                    cursor, 'rooms', ROOMS_SQL, options['rooms'], batch_size, {'offset': offset}
                )

            if options['guests']:
                offset = self._max_id(cursor, 'guests', 'id_guest')
                self._insert_batches(
                    cursor, 'guests', GUESTS_SQL, options['guests'], batch_size, {'offset': offset}
                )

            if options['bookings']:
                guest_count = self._temp_guest_ids(cursor)
                room_count = self._temp_room_ids(cursor)
                if not guest_count or not room_count:
                    raise CommandError('Для генерации бронирований нужны гости и комнаты.')
                self._insert_batches(
                    cursor,
                    'bookings',
                    BOOKINGS_SQL,
                    options['bookings'],
                    batch_size,
                    {'guest_count': guest_count, 'room_count': room_count},
                )

            if options['payments'] or options['booking_services']:
                booking_count = self._temp_booking_ids(cursor)
                if not booking_count:
                    raise CommandError('Для генерации платежей нужны бронирования.')

                if options['payments']:
                    self._insert_batches(
                        cursor,
                        'payments',
                        PAYMENTS_SQL,
                        options['payments'],
                        batch_size,
                        {'booking_count': booking_count},
                    )

                if options['booking_services']:
                    service_count = self._temp_service_ids(cursor)
                    if not service_count:
                        raise CommandError('Нет услуг. Сначала запустите manage.py seed_demo.')
                    self._insert_batches(
                        cursor,
                        'bookingservices',
                        BOOKING_SERVICES_SQL,
                        options['booking_services'],
                        batch_size,
                        {'booking_count': booking_count, 'service_count': service_count},
                    )

            self._drop_temp_tables(cursor)
            self.stdout.write('Обновление статистики (ANALYZE)...')
            cursor.execute('ANALYZE')

        self.stdout.write(self.style.SUCCESS('Генерация данных завершена.'))

    # ---------------------------------------------------------------- helpers

    def _max_id(self, cursor, table, column):
        """Сдвиг для уникальных значений, чтобы повторный запуск не ломался."""
        cursor.execute(f'SELECT COALESCE(MAX({column}), 0) FROM {table}')
        return cursor.fetchone()[0]

    def _count(self, cursor, table):
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        return cursor.fetchone()[0]

    def _insert_batches(self, cursor, label, sql, total, batch_size, params):
        started = time.monotonic()
        done = 0
        inserted = 0
        while done < total:
            chunk = min(batch_size, total - done)
            cursor.execute(sql, {**params, 'start': done + 1, 'end': done + chunk})
            inserted += cursor.rowcount
            done += chunk
            self.stdout.write(f'  {label}: {done}/{total}')
        elapsed = time.monotonic() - started
        self.stdout.write(
            self.style.SUCCESS(f'{label}: вставлено {inserted} строк за {elapsed:.1f} c')
        )

    def _temp_table(self, cursor, name, select_sql):
        cursor.execute(f'DROP TABLE IF EXISTS {name}')
        cursor.execute(f'CREATE TEMP TABLE {name} AS {select_sql}')
        cursor.execute(f'ALTER TABLE {name} ADD PRIMARY KEY (rn)')
        cursor.execute(f'ANALYZE {name}')
        return self._count(cursor, name)

    def _temp_guest_ids(self, cursor):
        return self._temp_table(
            cursor,
            'tmp_guest_ids',
            'SELECT row_number() OVER (ORDER BY id_guest) AS rn, id_guest FROM guests',
        )

    def _temp_room_ids(self, cursor):
        return self._temp_table(
            cursor,
            'tmp_room_ids',
            """
            SELECT row_number() OVER (ORDER BY r.id_room) AS rn, r.id_room, rt.price_per_night
            FROM rooms r
            JOIN roomtypes rt ON rt.id_type = r.id_type
            """,
        )

    def _temp_booking_ids(self, cursor):
        return self._temp_table(
            cursor,
            'tmp_booking_ids',
            """
            SELECT row_number() OVER (ORDER BY id_booking) AS rn, id_booking, total_price, check_in
            FROM bookings
            """,
        )

    def _temp_service_ids(self, cursor):
        return self._temp_table(
            cursor,
            'tmp_service_ids',
            'SELECT row_number() OVER (ORDER BY id_service) AS rn, id_service FROM services',
        )

    def _drop_temp_tables(self, cursor):
        for name in ('tmp_guest_ids', 'tmp_room_ids', 'tmp_booking_ids', 'tmp_service_ids'):
            cursor.execute(f'DROP TABLE IF EXISTS {name}')
