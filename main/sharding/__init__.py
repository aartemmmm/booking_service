"""
Шардирование бронирований между несколькими экземплярами PostgreSQL.

Ключ шардирования — id_guest: все брони одного гостя лежат на одном шарде.
"""

from django.conf import settings

from .router import ConsistentHashRouter, ModuloRouter, stable_hash

__all__ = ['ConsistentHashRouter', 'ModuloRouter', 'stable_hash', 'booking_router']


def booking_router():
    """
    Router, по которому сервис размещает и ищет брони.

    Используется стратегия hash(id_guest) % N. Смена стратегии или числа шардов
    меняет адрес части записей, поэтому их пришлось бы сначала перенести
    (см. manage.py shard_bookings rebalance).
    """
    return ModuloRouter(settings.BOOKING_SHARDS)
