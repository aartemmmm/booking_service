"""
Ручной запуск CreatePartitionsJob.

Логика job живёт в PostgreSQL — функция lab3.create_missing_partitions
(deploy/postgres/initdb/10-partitions-pg-cron.sql). По расписанию её вызывает
pg_cron, а эта команда вызывает ту же самую функцию вручную: для демонстрации
и для восстановления после сбоя. Поэтому ручной и плановый запуск не могут
разойтись в поведении.

Примеры:
    python manage.py create_partitions --schema lab3 --table events --granularity day --horizon 3
    python manage.py create_partitions --schema lab3 --table bookings_partitioned \
        --granularity month --horizon 3 --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

GRANULARITIES = ('day', 'month')


class Command(BaseCommand):
    help = 'Создать недостающие партиции (та же функция, что вызывает pg_cron).'

    def add_arguments(self, parser):
        parser.add_argument('--schema', default='lab3', help='Схема партиционированной таблицы')
        parser.add_argument('--table', default='events', help='Имя партиционированной таблицы')
        parser.add_argument(
            '--granularity', default='day', choices=GRANULARITIES,
            help='Период одной партиции: day или month',
        )
        parser.add_argument(
            '--horizon', type=int, default=3,
            help='Сколько периодов вперёд должно быть готово (3 дня = сегодня + 3 партиции)',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Только показать, что было бы создано, ничего не создавая',
        )

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT status, report FROM lab3.create_missing_partitions(%s, %s, %s, %s, %s)',
                    [
                        options['schema'],
                        options['table'],
                        options['granularity'],
                        options['horizon'],
                        options['dry_run'],
                    ],
                )
                status, report = cursor.fetchone()
        except DatabaseError as exc:
            # Первая строка — само сообщение, дальше служебный CONTEXT PL/pgSQL
            raise CommandError(str(exc).strip().splitlines()[0]) from exc

        self.stdout.write(report)
        if status == 'CREATED':
            self.stdout.write(self.style.SUCCESS('Недостающие партиции созданы.'))
