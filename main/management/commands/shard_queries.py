"""
Как ведут себя реальные запросы сервиса после шардирования bookings по id_guest.

Каждое действие берёт настоящий запрос сервиса и выполняет его на шардах
из лабораторной №5, показывая, сколько шардов затронуто и где объединяется результат.

    python manage.py shard_queries single --guest-id 29604   # запрос в один шард
    python manage.py shard_queries count                     # COUNT(*) по всем шардам
    python manage.py shard_queries join --guest-id 29604     # JOIN с таблицей другой базы
    python manage.py shard_queries top --limit 20            # ORDER BY ... LIMIT через merge
    python manage.py shard_queries failure --guest-id 29604  # что видит backend при отказе шарда
    python manage.py shard_queries hot                       # равные строки ≠ равная нагрузка

Все действия только читают данные. Шарды — settings.BOOKING_SHARDS,
основная база сервиса — 'default'.
"""

import heapq
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connections

from main.repositories import sharded_booking_repository as repo
from main.sharding import booking_router

# Запросы сервиса в той форме, в какой они уходят в PostgreSQL

COUNT_SQL = 'SELECT COUNT(*) FROM bookings WHERE status = %s'

# revenue_by_room_type без JOIN на rooms/roomtypes: на шарде их нет,
# группировать можно только по id_room, а имя типа подставить из основной базы
REVENUE_PARTIAL_SQL = """
    SELECT id_room, COUNT(*) AS cnt, SUM(total_price) AS revenue, SUM(total_price) AS sum_price
    FROM bookings
    GROUP BY id_room
"""

TOP_SQL = """
    SELECT id_booking, id_guest, created_at
    FROM bookings
    ORDER BY created_at DESC
    LIMIT %s
"""

TOP_GUESTS_PARTIAL_SQL = """
    SELECT id_guest, COUNT(*) AS bookings_count, SUM(total_price) AS total_spent
    FROM bookings
    GROUP BY id_guest
    ORDER BY total_spent DESC
    LIMIT %s
"""


def _fetch(alias, sql, params=None):
    with connections[alias].cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def _timed(alias, sql, params=None):
    started = time.perf_counter()
    rows = _fetch(alias, sql, params)
    return rows, (time.perf_counter() - started) * 1000


class Command(BaseCommand):
    help = 'Поведение реальных запросов сервиса на шардах: single-shard, COUNT, JOIN, ORDER BY LIMIT, отказ, hot shard.'

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        for name in ('single', 'join', 'failure'):
            sub = actions.add_parser(name)
            sub.add_argument('--guest-id', type=int, default=29604)
        actions.add_parser('count').add_argument('--status', default='confirmed')
        actions.add_parser('top').add_argument('--limit', type=int, default=20)
        actions.add_parser('hot')

    def handle(self, *args, **options):
        getattr(self, f'_{options["action"]}')(**options)

    def _head(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    # ------------------------------------------------------------ single

    def _single(self, guest_id, **_):
        self._head(f'Single-shard query: брони гостя {guest_id}')
        router = booking_router()
        shard = router.shard_for(guest_id)
        self.stdout.write(f'router: hash({guest_id}) % {len(router.shards)} → {shard}')

        started = time.perf_counter()
        found_on, rows = repo.list_bookings_of_guest(guest_id)
        elapsed = (time.perf_counter() - started) * 1000
        self.stdout.write(f'запрос выполнен на {found_on}, {len(rows)} строк, {elapsed:.2f} мс, '
                          f'шардов затронуто: 1 из {len(router.shards)}')

        self.stdout.write('проверка на остальных шардах (в реальной работе не нужна):')
        for other in settings.BOOKING_SHARDS:
            self.stdout.write(f'  {other}: {repo.count_on_shard(other, guest_id)} строк гостя')

    # ------------------------------------------------------------- count

    def _count(self, status, **_):
        shards = settings.BOOKING_SHARDS
        self._head(f"Агрегация: COUNT(*) WHERE status = '{status}' — как count_bookings() для пагинации")

        self.stdout.write('последовательно, шард за шардом:')
        total = 0
        seq_time = 0.0
        for shard in shards:
            rows, ms = _timed(shard, COUNT_SQL, [status])
            row = rows[0][0]
            total += row
            seq_time += ms
            self.stdout.write(f'  {shard} → {row:>7}   ({ms:.2f} мс)')
        self.stdout.write(f'  объединение в backend: сумма = {total}   суммарное время {seq_time:.2f} мс')

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(shards)) as pool:
            parts = list(pool.map(lambda s: _fetch(s, COUNT_SQL, [status])[0][0], shards))
        par_time = (time.perf_counter() - started) * 1000
        self.stdout.write(f'параллельно ко всем шардам: сумма = {sum(parts)}   время = {par_time:.2f} мс '
                          f'(самый медленный шард)')

        rows, ms = _timed('default', COUNT_SQL, [status])
        self.stdout.write(f'для сравнения, одна нешардированная база: {rows[0][0]}   ({ms:.2f} мс)')
        self.stdout.write('')
        self.stdout.write('GROUP BY: top_guests() — гости сгруппированы по id_guest, то есть по shard key:')
        limit = 3
        heap = []
        for shard in shards:
            rows, ms = _timed(shard, TOP_GUESTS_PARTIAL_SQL, [limit])
            self.stdout.write(f'  {shard} top-{limit}: ' + ', '.join(f'{g}={s}' for g, _, s in rows) + f'   ({ms:.2f} мс)')
            heap.extend((float(spent), guest, cnt) for guest, cnt, spent in rows)
        merged = heapq.nlargest(limit, heap)
        self.stdout.write('  merge в backend → top-3: ' + ', '.join(f'{g}={Decimal(s):.2f}' for s, g, _ in merged))

    # -------------------------------------------------------------- join

    def _join(self, guest_id, **_):
        self._head('JOIN: карточка брони — bookings JOIN guests JOIN rooms (get_booking)')
        shard = booking_router().shard_for(guest_id)
        rows = _fetch(shard, 'SELECT id_booking, id_guest, id_room FROM bookings WHERE id_guest = %s LIMIT 1',
                      [guest_id])
        if not rows:
            self.stdout.write('у гостя нет броней')
            return
        booking_id, gid, room_id = rows[0]
        self.stdout.write(f'бронь {booking_id} лежит на {shard}; guests и rooms — только в основной базе')

        self.stdout.write('попытка выполнить JOIN сервиса одним SQL прямо на шарде:')
        try:
            _fetch(shard, 'SELECT b.id_booking, g.last_name FROM bookings b '
                          'JOIN guests g ON g.id_guest = b.id_guest WHERE b.id_booking = %s', [booking_id])
        except DatabaseError as exc:
            self.stdout.write('  ' + self.style.ERROR(str(exc).strip().splitlines()[0]))

        self.stdout.write('как приходится делать: два запроса и склейка в backend')
        started = time.perf_counter()
        (guest,) = _fetch('default', 'SELECT last_name || \' \' || first_name FROM guests WHERE id_guest = %s', [gid])
        (room,) = _fetch('default', 'SELECT room_number FROM rooms WHERE id_room = %s', [room_id])
        elapsed = (time.perf_counter() - started) * 1000
        self.stdout.write(f'  {shard}: бронь {booking_id}  +  default: гость «{guest[0]}», комната {room[0]}  '
                          f'({elapsed:.2f} мс, 2 дополнительных запроса)')

        self.stdout.write('')
        self.stdout.write('JOIN bookings → payments (get_booking считает оплату): payments не шардированы,')
        (paid,) = _fetch('default', "SELECT COALESCE(SUM(amount),0) FROM payments WHERE id_booking = %s AND status='success'",
                         [booking_id])
        self.stdout.write(f'  оплата брони {booking_id} берётся из основной базы отдельно: {paid[0]}')

    # --------------------------------------------------------------- top

    def _top(self, limit, **_):
        shards = settings.BOOKING_SHARDS
        self._head(f'ORDER BY created_at DESC LIMIT {limit} — лента GET /api/bookings')

        per_shard = {}
        for shard in shards:
            rows, ms = _timed(shard, TOP_SQL, [limit])
            per_shard[shard] = rows
            self.stdout.write(f'  {shard} → top-{limit}, самая свежая {rows[0][2]:%Y-%m-%d %H:%M:%S}   ({ms:.2f} мс)')

        merged = heapq.nlargest(limit, (r for rows in per_shard.values() for r in rows), key=lambda r: r[2])
        truth = _fetch('default', TOP_SQL, [limit])
        truth_ids = [r[0] for r in truth]
        self.stdout.write(f'  merge {len(shards)}×{limit} = {len(shards) * limit} строк → top-{limit}')

        merged_ids = [r[0] for r in merged]
        self.stdout.write(f'  совпадает с одной нешардированной базой: {merged_ids == truth_ids}')

        self.stdout.write('')
        self.stdout.write(f'откуда взялись настоящие top-{limit}:')
        origin = {}
        for shard, rows in per_shard.items():
            ids = {r[0] for r in rows}
            origin[shard] = sum(1 for i in truth_ids if i in ids)
            self.stdout.write(f'  {shard}: {origin[shard]} из {limit}')
        best = max(origin, key=origin.get)
        self.stdout.write(f'  → взяв top-{limit} только с {best}, получили бы верных {origin[best]} из {limit}, '
                          f'остальные {limit - origin[best]} — не самые свежие брони')

    # ----------------------------------------------------------- failure

    def _failure(self, guest_id, **_):
        shards = settings.BOOKING_SHARDS
        self._head('Отказ шарда: что видит backend')
        for shard in shards:
            try:
                rows, ms = _timed(shard, 'SELECT COUNT(*) FROM bookings')
                self.stdout.write(f'  {shard}: доступен, {rows[0][0]} строк ({ms:.1f} мс)')
            except DatabaseError as exc:
                self.stdout.write(f'  {shard}: ' + self.style.ERROR('НЕДОСТУПЕН — ' + str(exc).strip().splitlines()[0]))

        self.stdout.write('')
        router = booking_router()
        for gid in (guest_id, 101, 102):
            shard = router.shard_for(gid)
            try:
                _, rows = repo.list_bookings_of_guest(gid)
                self.stdout.write(f'  брони гостя {gid} ({shard}): OK, {len(rows)} строк')
            except DatabaseError as exc:
                self.stdout.write(f'  брони гостя {gid} ({shard}): ' + self.style.ERROR('ошибка — ' + str(exc).strip().splitlines()[0]))

        self.stdout.write('')
        total, failed = 0, []
        for shard in shards:
            try:
                total += _fetch(shard, 'SELECT COUNT(*) FROM bookings')[0][0]
            except DatabaseError:
                failed.append(shard)
        if failed:
            self.stdout.write(f'  COUNT(*) по всем шардам: ' + self.style.WARNING(
                f'неполный результат {total} — недоступны {", ".join(failed)}'))
        else:
            self.stdout.write(f'  COUNT(*) по всем шардам: {total}')

    # --------------------------------------------------------------- hot

    def _hot(self, **_):
        shards = settings.BOOKING_SHARDS
        self._head('Hot shard: равное число строк ≠ равная нагрузка')
        rows_per_shard = {s: repo.count_on_shard(s) for s in shards}
        total_rows = sum(rows_per_shard.values())
        self.stdout.write('строки по шардам: ' + ', '.join(
            f'{s} {n} ({100 * n / total_rows:.1f}%)' for s, n in rows_per_shard.items()))

        # Модель нагрузки: каждый гость открывает свои брони; сколько раз — пропорционально
        # числу его броней в статусе pending/confirmed (активные брони смотрят чаще).
        self.stdout.write('')
        self.stdout.write("модель нагрузки 1: запросы ∝ активным броням гостя (status pending/confirmed)")
        load = {}
        for s in shards:
            (n,) = _fetch(s, "SELECT COUNT(*) FROM bookings WHERE status IN ('pending','confirmed')")[0]
            load[s] = n
        t = sum(load.values())
        self.stdout.write('  ' + ', '.join(f'{s} {100 * n / t:.1f}%' for s, n in load.items()))

        self.stdout.write('модель нагрузки 2: один популярный гость даёт половину всех запросов')
        router = booking_router()
        top = _fetch('default', 'SELECT id_guest, COUNT(*) FROM bookings GROUP BY id_guest ORDER BY 2 DESC LIMIT 1')[0]
        hot_shard = router.shard_for(top[0])
        base = {s: 50.0 * rows_per_shard[s] / total_rows for s in shards}
        base[hot_shard] += 50.0
        self.stdout.write(f'  самый активный гость {top[0]} ({top[1]} броней) лежит на {hot_shard}')
        self.stdout.write('  → ' + ', '.join(f'{s} {v:.1f}%' for s, v in base.items()))

        self.stdout.write('модель нагрузки 3: запросы без shard key (лента, отчёты) — идут на все шарды')
        self.stdout.write('  каждый такой запрос нагружает все три шарда сразу, независимо от размещения данных')
