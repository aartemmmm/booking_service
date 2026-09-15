"""
Шардирование бронирований по id_guest.

    python manage.py shard_bookings load                # разложить брони сервиса по шардам
    python manage.py shard_bookings stats               # сколько броней на каждом шарде
    python manage.py shard_bookings route --guest-id 29604 --guest-id 101
                                                        # куда router отправляет гостя
    python manage.py shard_bookings rebalance           # сколько записей переедет
                                                        # при изменении числа шардов

load берёт брони из основной базы сервиса (public.bookings) и через router
раскладывает по шардам стратегией hash(id_guest) % N.

rebalance ничего не переносит: по данным, лежащим на шардах, считает, у скольких
записей изменится шард для hash % N и для Consistent Hashing.
"""

import time
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from main.repositories import sharded_booking_repository as repo
from main.sharding import ConsistentHashRouter, ModuloRouter, booking_router, stable_hash

BATCH_SIZE = 20000

SOURCE_SQL = f"""
    SELECT {", ".join(repo.COLUMNS)}
    FROM bookings
    WHERE id_booking > %s
    ORDER BY id_booking
    LIMIT %s
"""


def _pct(part, total):
    return 100.0 * part / total if total else 0.0


class Command(BaseCommand):
    help = 'Шардирование бронирований: загрузка, статистика, маршрут, расчёт переноса.'

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)

        actions.add_parser('load', help='Разложить брони основной базы по шардам')
        actions.add_parser('stats', help='Распределение броней по шардам')

        route = actions.add_parser('route', help='На какой шард попадает гость')
        route.add_argument('--guest-id', type=int, action='append', required=True,
                           help='id гостя; можно указать несколько раз')

        rebalance = actions.add_parser('rebalance', help='Сколько записей переедет при смене N')
        rebalance.add_argument('--vnodes', type=int, default=100,
                               help='Число virtual nodes на шард для сравнения (по умолчанию 100)')

    def handle(self, *args, **options):
        getattr(self, f'_{options["action"]}')(**options)

    # ------------------------------------------------------------------ load

    def _load(self, **options):
        shards = settings.BOOKING_SHARDS
        self.stdout.write(f'Router: {booking_router()!r}, шарды: {", ".join(shards)}')

        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT count(*) FROM bookings')
            source_total = cursor.fetchone()[0]
        self.stdout.write(f'Броней в основной базе сервиса: {source_total}')

        self.stdout.write('Очистка таблиц bookings на шардах...')
        repo.truncate_all()

        started = time.monotonic()
        loaded = Counter()
        last_id = 0
        while True:
            with connections['default'].cursor() as cursor:
                cursor.execute(SOURCE_SQL, [last_id, BATCH_SIZE])
                rows = cursor.fetchall()
            if not rows:
                break
            loaded.update(repo.insert_bookings(rows))
            last_id = rows[-1][0]
            self.stdout.write(f'  загружено {sum(loaded.values())}/{source_total}')

        elapsed = time.monotonic() - started
        total = sum(loaded.values())
        self.stdout.write(self.style.SUCCESS(f'Загружено {total} броней за {elapsed:.1f} с'))
        if total != source_total:
            raise CommandError(f'Загружено {total}, а в основной базе {source_total}.')
        self._print_distribution(repo.count_by_shard())

    # ----------------------------------------------------------------- stats

    def _stats(self, **options):
        counts = repo.count_by_shard()
        self._print_distribution(counts)

        # Проверка размещения: каждая бронь должна лежать там, куда её отправляет router
        router = booking_router()
        misplaced = 0
        for shard in settings.BOOKING_SHARDS:
            for guest_id, count in repo.guest_counts(shard):
                if router.shard_for(guest_id) != shard:
                    misplaced += count
        verdict = self.style.SUCCESS('все на своих шардах') if misplaced == 0 else \
            self.style.ERROR(f'не на своём шарде: {misplaced}')
        self.stdout.write(f'Проверка размещения по router: {verdict}')

    def _print_distribution(self, counts):
        total = sum(counts.values())
        mean = total / len(counts) if counts else 0
        self.stdout.write('')
        self.stdout.write(f'{"Шард":10} {"Броней":>9} {"Доля":>8} {"От среднего":>12}')
        for shard, count in counts.items():
            self.stdout.write(
                f'{shard:10} {count:>9} {_pct(count, total):>7.2f}% '
                f'{_pct(count - mean, mean):>+11.2f}%'
            )
        self.stdout.write(f'{"Всего":10} {total:>9}')
        if counts and min(counts.values()):
            self.stdout.write(
                f'Самый большой шард больше самого маленького в '
                f'{max(counts.values()) / min(counts.values()):.4f} раза'
            )

    # ----------------------------------------------------------------- route

    def _route(self, **options):
        router = booking_router()
        n = len(router.shards)
        for guest_id in options['guest_id']:
            h = stable_hash(guest_id)
            shard = router.shard_for(guest_id)
            self.stdout.write('')
            self.stdout.write(f'id_guest = {guest_id}')
            self.stdout.write(f'  hash({guest_id}) = {h}')
            self.stdout.write(f'  hash({guest_id}) % {n} = {h % n}  →  {shard}')

            found_on, rows = repo.list_bookings_of_guest(guest_id)
            self.stdout.write(f'  запрос броней гостя выполнен на {found_on}: {len(rows)} шт.')
            for row in rows[:3]:
                self.stdout.write(
                    f'    id_booking={row["id_booking"]} room={row["id_room"]} '
                    f'{row["check_in"]}..{row["check_out"]} {row["status"]}'
                )

            with connections['default'].cursor() as cursor:
                cursor.execute('SELECT count(*) FROM bookings WHERE id_guest = %s', [guest_id])
                in_source = cursor.fetchone()[0]
            per_shard = {s: repo.count_on_shard(s, guest_id) for s in settings.BOOKING_SHARDS}
            layout = ', '.join(f'{s}: {c}' for s, c in per_shard.items())
            self.stdout.write(f'  броней гостя по шардам: {layout}; в основной базе: {in_source}')

    # ------------------------------------------------------------- rebalance

    def _rebalance(self, **options):
        vnodes = options['vnodes']
        keys = []
        for shard in settings.BOOKING_SHARDS:
            keys.extend(repo.guest_counts(shard))
        total = sum(count for _, count in keys)
        if not total:
            raise CommandError('Шарды пусты — сначала выполните shard_bookings load.')

        self.stdout.write(f'Данные с шардов: {total} броней, {len(keys)} разных id_guest')

        three = ['shard_0', 'shard_1', 'shard_2']
        four = three + ['shard_3']
        five = four + ['shard_4']
        two = ['shard_0', 'shard_2']

        strategies = [
            ('hash(key) % N', lambda shards: ModuloRouter(shards)),
            ('Consistent Hashing', lambda shards: ConsistentHashRouter(shards, vnodes=1)),
            (f'CH, {vnodes} vnodes', lambda shards: ConsistentHashRouter(shards, vnodes=vnodes)),
        ]

        self._section('Распределение на 3 шардах')
        for name, make in strategies:
            counts = self._distribution(keys, make(three))
            self._distribution_line(name, counts, total)

        self._section('Доля кольца у каждого шарда (Consistent Hashing)')
        for label, shards in (('3 шарда', three), ('4 шарда', four)):
            for vn in (1, vnodes):
                ring = ConsistentHashRouter(shards, vnodes=vn)
                share = ', '.join(f'{s} {100 * v:.1f}%' for s, v in ring.ring_share().items())
                self.stdout.write(f'  {label}, vnodes={vn:<4} {share}')

        scenarios = [
            ('Добавление шарда: 3 → 4 (shard_3)', three, four),
            ('Добавление ещё одного: 4 → 5 (shard_4)', four, five),
            ('Удаление шарда: 3 → 2 (shard_1)', three, two),
        ]
        for title, old, new in scenarios:
            self._section(title)
            self.stdout.write(
                f'  {"Стратегия":22} {"Перемещено":>11} {"%":>8} {"Ключей":>8}   '
                f'{"в новый / из удалённого":>24} {"между прочими":>14}'
            )
            for name, make in strategies:
                result = self._simulate(keys, make(old), make(new), old, new)
                self.stdout.write(
                    f'  {name:22} {result["moved"]:>11} {_pct(result["moved"], total):>7.2f}% '
                    f'{result["moved_keys"]:>8}   {result["expected_flow"]:>24} '
                    f'{result["other_flow"]:>14}'
                )
            self.stdout.write('  Распределение после изменения:')
            for name, make in strategies:
                self._distribution_line(name, self._distribution(keys, make(new)), total, indent=4)

    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    @staticmethod
    def _distribution(keys, router):
        counts = Counter({shard: 0 for shard in router.shards})
        for guest_id, count in keys:
            counts[router.shard_for(guest_id)] += count
        return counts

    def _distribution_line(self, name, counts, total, indent=2):
        parts = '  '.join(f'{s} {c:>6} ({_pct(c, total):5.2f}%)' for s, c in counts.items())
        self.stdout.write(f'{" " * indent}{name:22} {parts}')

    @staticmethod
    def _simulate(keys, old_router, new_router, old_shards, new_shards):
        added = set(new_shards) - set(old_shards)
        removed = set(old_shards) - set(new_shards)
        moved = moved_keys = expected = other = 0
        for guest_id, count in keys:
            before = old_router.shard_for(guest_id)
            after = new_router.shard_for(guest_id)
            if before == after:
                continue
            moved += count
            moved_keys += 1
            # «Ожидаемый» перенос: в добавленный шард или из удалённого.
            # Всё остальное — перетасовка между шардами, которые не менялись.
            if after in added or before in removed:
                expected += count
            else:
                other += count
        return {
            'moved': moved, 'moved_keys': moved_keys,
            'expected_flow': expected, 'other_flow': other,
        }
