"""
Состояние репликации Primary → Replica и измерение replication lag.

    python manage.py replication_status             # состояние обоих подключений
    python manage.py replication_status --probe 50  # 50 циклов: INSERT на Primary,
                                                    # сразу SELECT на Replica

Проба показывает, видно ли изменение на Replica немедленно после фиксации
на Primary, и сколько времени проходит до его появления. Строки пишутся
в служебную таблицу lab4.replication_probe.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from main.repositories.base import PRIMARY, REPLICA

# Сколько отдельных случаев отставания печатать подробно
MAX_DETAILS = 10

PROBE_TABLE_SQL = """
    CREATE SCHEMA IF NOT EXISTS lab4;
    CREATE TABLE IF NOT EXISTS lab4.replication_probe (
        id      BIGSERIAL PRIMARY KEY,
        sent_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    )
"""


def _fetch_one(alias, sql, params=None):
    with connections[alias].cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchone()


def _fetch_all(alias, sql):
    with connections[alias].cursor() as cursor:
        cursor.execute(sql)
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


class Command(BaseCommand):
    help = 'Показать состояние репликации и измерить отставание Replica от Primary.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--probe', type=int, default=0, metavar='N',
            help='Выполнить N циклов INSERT(Primary) → SELECT(Replica) и измерить задержку',
        )
        parser.add_argument(
            '--timeout', type=float, default=10.0,
            help='Сколько секунд ждать появления строки на Replica в одном цикле',
        )

    # --------------------------------------------------------------- status

    def _describe(self, alias):
        db = settings.DATABASES[alias]
        in_recovery, version = _fetch_one(
            alias, "SELECT pg_is_in_recovery(), current_setting('server_version')"
        )
        role = 'Replica (hot standby)' if in_recovery else 'Primary'
        self.stdout.write(f'{alias:8s} {db["HOST"]}:{db["PORT"]}  PostgreSQL {version}  → {role}')
        return in_recovery

    def _show_status(self):
        self.stdout.write('Подключения:')
        primary_in_recovery = self._describe(PRIMARY)
        replica_in_recovery = self._describe(REPLICA)
        self.stdout.write('')

        if primary_in_recovery:
            self.stdout.write(self.style.ERROR(
                "Подключение 'default' ведёт на standby — записи будут отклоняться."
            ))
        if not replica_in_recovery:
            self.stdout.write(self.style.WARNING(
                "Подключение 'replica' ведёт не на standby: реплика не настроена, "
                'чтение идёт с Primary.'
            ))

        self.stdout.write('pg_stat_replication на Primary:')
        rows = _fetch_all(PRIMARY, """
            SELECT application_name, client_addr::text AS client_addr, state, sync_state,
                   sent_lsn::text, write_lsn::text, flush_lsn::text, replay_lsn::text,
                   pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes,
                   write_lag::text, flush_lag::text, replay_lag::text
            FROM pg_stat_replication
        """)
        if not rows:
            self.stdout.write('  (нет подключённых реплик)')
        for r in rows:
            self.stdout.write(
                f'  {r["application_name"]} c {r["client_addr"]}: state={r["state"]}, '
                f'sync_state={r["sync_state"]}\n'
                f'    sent={r["sent_lsn"]} write={r["write_lsn"]} '
                f'flush={r["flush_lsn"]} replay={r["replay_lsn"]}\n'
                f'    отставание replay: {r["replay_lag_bytes"]} байт; '
                f'write_lag={r["write_lag"]} flush_lag={r["flush_lag"]} replay_lag={r["replay_lag"]}'
            )
        self.stdout.write('')

        if replica_in_recovery:
            self.stdout.write('Состояние Replica:')
            row = _fetch_one(REPLICA, """
                SELECT pg_last_wal_receive_lsn()::text,
                       pg_last_wal_replay_lsn()::text,
                       pg_last_xact_replay_timestamp()::text,
                       (now() - pg_last_xact_replay_timestamp())::text,
                       pg_is_wal_replay_paused()
            """)
            self.stdout.write(
                f'  получено WAL до: {row[0]}\n'
                f'  воспроизведено до: {row[1]}\n'
                f'  последняя воспроизведённая транзакция: {row[2]} (назад: {row[3]})\n'
                f'  воспроизведение приостановлено: {row[4]}'
            )
            self.stdout.write('')

    # ---------------------------------------------------------------- probe

    def _wait_table_on_replica(self, timeout):
        """
        DDL тоже приходит на Replica через WAL: сразу после CREATE TABLE на Primary
        таблицы на Replica ещё может не быть. Дождаться её появления.
        """
        started = time.perf_counter()
        while True:
            row = _fetch_one(REPLICA, "SELECT to_regclass('lab4.replication_probe')")
            if row and row[0] is not None:
                return (time.perf_counter() - started) * 1000
            if time.perf_counter() - started > timeout:
                raise CommandError('Таблица lab4.replication_probe не появилась на Replica.')
            time.sleep(0.005)

    def _probe(self, count, timeout):
        with connections[PRIMARY].cursor() as cursor:
            cursor.execute(PROBE_TABLE_SQL)
        waited_ms = self._wait_table_on_replica(timeout)
        if waited_ms > 1:
            self.stdout.write(
                f'Таблица пробы появилась на Replica через {waited_ms:.1f} мс после '
                'создания на Primary (DDL тоже воспроизводится из WAL).'
            )

        self.stdout.write(f'Проба: {count} циклов INSERT на Primary → SELECT на Replica')
        immediate = 0
        delays = []
        lost = 0

        for _ in range(count):
            row_id, = _fetch_one(
                PRIMARY, 'INSERT INTO lab4.replication_probe DEFAULT VALUES RETURNING id'
            )
            committed_at = time.perf_counter()

            attempts = 0
            while True:
                attempts += 1
                found = _fetch_one(
                    REPLICA, 'SELECT 1 FROM lab4.replication_probe WHERE id = %s', [row_id]
                )
                if found:
                    delay_ms = (time.perf_counter() - committed_at) * 1000
                    if attempts == 1:
                        immediate += 1
                    else:
                        delays.append(delay_ms)
                        if len(delays) <= MAX_DETAILS:
                            self.stdout.write(
                                f'  id={row_id}: первый SELECT не увидел строку, '
                                f'появилась через {delay_ms:.2f} мс (попыток: {attempts})'
                            )
                    break
                if time.perf_counter() - committed_at > timeout:
                    lost += 1
                    self.stdout.write(self.style.ERROR(
                        f'  id={row_id}: строка не появилась за {timeout} с'
                    ))
                    break

        if len(delays) > MAX_DETAILS:
            self.stdout.write(f'  ... и ещё {len(delays) - MAX_DETAILS} таких случаев')
        self.stdout.write('')
        self.stdout.write(f'Видно сразу первым SELECT: {immediate} из {count}')
        self.stdout.write(f'Первый SELECT увидел старые данные: {len(delays)} из {count}')
        if delays:
            self.stdout.write(
                f'Задержка появления: min {min(delays):.2f} мс, '
                f'avg {sum(delays) / len(delays):.2f} мс, max {max(delays):.2f} мс'
            )
        if lost:
            self.stdout.write(self.style.ERROR(f'Не дождались: {lost}'))

    def handle(self, *args, **options):
        self._show_status()
        if options['probe'] > 0:
            self._probe(options['probe'], options['timeout'])
