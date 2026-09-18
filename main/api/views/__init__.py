"""
HTTP-слой (контроллеры).

Обработчики не обращаются к базе напрямую: они разбирают запрос,
вызывают сервисный слой и сериализуют результат в JSON.

Пакет разбит по ресурсам API; здесь собраны все обработчики, чтобы
маршруты в main/urls.py и handler404/handler500 в booking_service/urls.py
обращались к ним по-прежнему как `views.<имя>`.
"""

from .bookings import (
    booking_item,
    booking_payments,
    booking_service_item,
    booking_services,
    bookings_collection,
)
from .errors import not_found, server_error
from .guests import guest_bookings, guest_item, guests_collection
from .payments import payment_item, payments_collection
from .reports import revenue_by_room_type, top_guests
from .rooms import (
    room_bookings,
    room_item,
    room_type_item,
    room_types_collection,
    rooms_collection,
)
from .services import service_item, services_collection
from .system import docs, health, openapi_spec

__all__ = [
    # служебные
    'health',
    'docs',
    'openapi_spec',
    # bookings
    'bookings_collection',
    'booking_item',
    'booking_services',
    'booking_service_item',
    'booking_payments',
    # guests
    'guests_collection',
    'guest_item',
    'guest_bookings',
    # rooms
    'rooms_collection',
    'room_item',
    'room_bookings',
    'room_types_collection',
    'room_type_item',
    # services
    'services_collection',
    'service_item',
    # payments
    'payments_collection',
    'payment_item',
    # reports
    'revenue_by_room_type',
    'top_guests',
    # обработчики ошибок
    'not_found',
    'server_error',
]
