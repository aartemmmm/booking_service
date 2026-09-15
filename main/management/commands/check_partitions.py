"""
Ручной запуск PartitionHealthCheck.

Проверка живёт в PostgreSQL — функция lab3.check_partitions
(deploy/postgres/initdb/10-partitions-pg-cron.sql). По расписанию её вызывает
pg_cron, эта команда вызывает ту же функцию вручную.

При смене состояния функция кладёт уведомление в таблицу lab3.partition_alerts
и подаёт сигнал NOTIFY partition_alert. Письмо отправляет слушатель
(manage.py partition_alert_listener, сервис partition-alerts в docker-compose).

Код возврата: 0 — OK, 1 — CRITICAL.

Пример:
    python manage.py check_partitions --schema lab3 --table events --granularity day --horizon 3
"""

import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

GRANULARITIES = ('day', 'month')


class Command(BaseCommand):
    help = 'Проверить наличие требуемых партиций (та же функция, что вызывает pg_cron).'

    def add_arguments(self, parser):
        parser.add_argument('--schema', default='lab3', help='Схема партиционированной таблицы')
        parser.add_argument('--table', default='events', help='Имя партиционированной таблицы')
        parser.add_argument(
            '--granularity', default='day', choices=GRANULARITIES,
            help='Период одной партиции: day или month',
        )
        parser.add_argument(
            '--horizon', type=int, default=3,
            help='Сколько периодов вперёд должно быть готово',
        )
        parser.add_argument(
            '--no-fail', action='store_true',
            help='Всегда возвращать код 0, даже при CRITICAL',
        )

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT status, report FROM lab3.check_partitions(%s, %s, %s, %s)',
                    [options['schema'], options['table'], options['granularity'], options['horizon']],
                )
                status, report = cursor.fetchone()
        except DatabaseError as exc:
            # Первая строка — само сообщение, дальше служебный CONTEXT PL/pgSQL
            raise CommandError(str(exc).strip().splitlines()[0]) from exc

        style = self.style.ERROR if status == 'CRITICAL' else self.style.SUCCESS
        self.stdout.write(style(report))

        if status == 'CRITICAL' and not options['no_fail']:
            sys.exit(1)
