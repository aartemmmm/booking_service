"""
Брони на шардах: запись и чтение через router.

Каждая операция сначала спрашивает у router, на каком шарде лежит гость,
и выполняет SQL только на этом экземпляре PostgreSQL.
"""

from collections import defaultdict

from django.conf import settings
from django.db import connections, transaction
from psycopg2.extras import execute_values

from main.sharding import booking_router

COLUMNS = (
    'id_booking', 'id_guest', 'id_room', 'check_in', 'check_out',
    'total_price', 'status', 'created_at', 'updated_at',
)
_GUEST_INDEX = COLUMNS.index('id_guest')


def shard_of_guest(guest_id):
    """Имя шарда (подключения), на котором лежат брони гостя."""
    return booking_router().shard_for(guest_id)


def insert_bookings(rows):
    """
    Разложить брони по шардам и вставить.

    rows — кортежи в порядке COLUMNS. Возвращает {шард: число вставленных строк}.
    """
    router = booking_router()
    by_shard = defaultdict(list)
    for row in rows:
        by_shard[router.shard_for(row[_GUEST_INDEX])].append(row)

    sql = f'INSERT INTO bookings ({", ".join(COLUMNS)}) VALUES %s'
    for shard, shard_rows in by_shard.items():
        with transaction.atomic(using=shard), connections[shard].cursor() as cursor:
            execute_values(cursor.cursor, sql, shard_rows, page_size=5000)
    return {shard: len(shard_rows) for shard, shard_rows in by_shard.items()}


def list_bookings_of_guest(guest_id):
    """Брони гостя: запрос уходит ровно на один шард. Возвращает (шард, строки)."""
    shard = shard_of_guest(guest_id)
    with connections[shard].cursor() as cursor:
        cursor.execute(
            f'SELECT {", ".join(COLUMNS)} FROM bookings '
            'WHERE id_guest = %s ORDER BY created_at DESC',
            [guest_id],
        )
        names = [col[0] for col in cursor.description]
        return shard, [dict(zip(names, row)) for row in cursor.fetchall()]


def count_on_shard(shard, guest_id=None):
    with connections[shard].cursor() as cursor:
        if guest_id is None:
            cursor.execute('SELECT count(*) FROM bookings')
        else:
            cursor.execute('SELECT count(*) FROM bookings WHERE id_guest = %s', [guest_id])
        return cursor.fetchone()[0]


def count_by_shard():
    """Сколько броней на каждом шарде."""
    return {shard: count_on_shard(shard) for shard in settings.BOOKING_SHARDS}


def guest_counts(shard):
    """[(id_guest, число броней), ...] на шарде — нужно для расчёта переноса."""
    with connections[shard].cursor() as cursor:
        cursor.execute('SELECT id_guest, count(*) FROM bookings GROUP BY id_guest')
        return cursor.fetchall()


def truncate_all():
    for shard in settings.BOOKING_SHARDS:
        with connections[shard].cursor() as cursor:
            cursor.execute('TRUNCATE bookings')
