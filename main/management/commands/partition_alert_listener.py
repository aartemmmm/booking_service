"""
Доставка уведомлений о состоянии партиций.

Проверку партиций по расписанию выполняет pg_cron внутри PostgreSQL
(функция lab3.check_partitions). Сама база отправлять письма не умеет, поэтому
при смене состояния функция кладёт уведомление в таблицу lab3.partition_alerts
и подаёт сигнал NOTIFY partition_alert. Эта команда держит подключение к базе,
слушает канал и отправляет письма через email-бэкенд Django.

Сигнал NOTIFY не сохраняется: если слушатель был выключен в момент проверки,
сигнал пропадёт. Поэтому источник истины — таблица, а сигнал лишь будит
слушателя. При старте, после переподключения и по таймауту отправляются
все неотправленные записи.

Запуск:
    python manage.py partition_alert_listener          # работать постоянно
    python manage.py partition_alert_listener --once   # отправить очередь и выйти
"""

import select
import time

import psycopg2
from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

CHANNEL = 'partition_alert'

NEXT_PENDING_SQL = """
    SELECT id, kind, target, subject, body
    FROM lab3.partition_alerts
    WHERE sent_at IS NULL
    ORDER BY id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
"""


class Command(BaseCommand):
    help = 'Слушать сигналы pg_cron-проверки партиций и отправлять уведомления.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once', action='store_true',
            help='Отправить все накопившиеся уведомления и завершиться',
        )
        parser.add_argument(
            '--timeout', type=int, default=60,
            help='Как часто, в секундах, проверять очередь без сигнала',
        )

    def _connect(self):
        db = settings.DATABASES['default']
        conn = psycopg2.connect(
            dbname=db['NAME'], user=db['USER'], password=db['PASSWORD'],
            host=db['HOST'], port=db['PORT'],
        )
        conn.autocommit = True
        return conn

    def _deliver_pending(self, conn):
        recipients = settings.PARTITION_ALERT_RECIPIENTS
        if not recipients:
            self.stderr.write('Получатели не заданы (PARTITION_ALERT_RECIPIENTS), отправка пропущена.')
            return 0

        delivered = 0
        while True:
            # Каждое уведомление — отдельная транзакция: строка блокируется,
            # письмо отправляется, строка помечается отправленной. Если отправка
            # упадёт, транзакция откатится и уведомление останется в очереди.
            conn.autocommit = False
            try:
                with conn.cursor() as cursor:
                    cursor.execute(NEXT_PENDING_SQL)
                    row = cursor.fetchone()
                    if row is None:
                        conn.rollback()
                        return delivered

                    alert_id, kind, target, subject, body = row
                    send_mail(
                        subject=subject,
                        message=body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=recipients,
                        fail_silently=False,
                    )
                    cursor.execute(
                        'UPDATE lab3.partition_alerts SET sent_at = now() WHERE id = %s', [alert_id]
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = True

            delivered += 1
            self.stdout.write(self.style.SUCCESS(
                f'Отправлено уведомление id={alert_id} [{kind}] {target} -> {", ".join(recipients)}'
            ))

    def handle(self, *args, **options):
        if options['once']:
            conn = self._connect()
            try:
                count = self._deliver_pending(conn)
            finally:
                conn.close()
            self.stdout.write(f'Отправлено уведомлений: {count}')
            return

        while True:
            try:
                conn = self._connect()
            except psycopg2.OperationalError as exc:
                self.stderr.write(f'Нет подключения к базе: {str(exc).strip()}. Повтор через 5 с.')
                time.sleep(5)
                continue

            try:
                with conn.cursor() as cursor:
                    cursor.execute(f'LISTEN {CHANNEL}')
                self.stdout.write(f'Слушаю канал {CHANNEL}.')

                # Всё, что накопилось, пока слушатель был выключен
                self._deliver_pending(conn)

                while True:
                    ready, _, _ = select.select([conn], [], [], options['timeout'])
                    if ready:
                        conn.poll()
                        conn.notifies.clear()
                    # И по сигналу, и по таймауту проверяем очередь целиком
                    self._deliver_pending(conn)
            except (psycopg2.Error, OSError) as exc:
                self.stderr.write(f'Ошибка: {str(exc).strip()}. Переподключение через 5 с.')
                time.sleep(5)
            finally:
                conn.close()
