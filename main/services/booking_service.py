"""Бизнес-логика бронирований — основной растущей сущности сервиса."""

from django.db import IntegrityError, transaction

from ..models import BOOKING_STATUSES
from ..repositories import (
    booking_repository,
    guest_repository,
    payment_repository,
    room_repository,
    service_repository,
)
from .errors import Conflict, NotFound, ValidationFailed
from .pagination import page_response, parse_page_params
from .validation import (
    as_date,
    as_int,
    as_optional_date,
    as_optional_int,
    day_bounds,
    one_of,
)


def _parse_filters(query):
    filters = {}

    status = query.get('status')
    if status:
        filters['status'] = one_of(status, BOOKING_STATUSES, 'status')

    filters['guest_id'] = as_optional_int(query.get('guest_id'), 'guest_id', 1)
    filters['room_id'] = as_optional_int(query.get('room_id'), 'room_id', 1)
    filters['room_type_id'] = as_optional_int(query.get('room_type_id'), 'room_type_id', 1)

    check_in_from = as_optional_date(query.get('check_in_from'), 'check_in_from')
    check_in_to = as_optional_date(query.get('check_in_to'), 'check_in_to')
    if check_in_from and check_in_to and check_in_from > check_in_to:
        raise ValidationFailed('"check_in_from" не может быть позже "check_in_to".')
    filters['check_in_from'] = check_in_from
    filters['check_in_to'] = check_in_to

    created_from = as_optional_date(query.get('created_from'), 'created_from')
    created_to = as_optional_date(query.get('created_to'), 'created_to')
    if created_from and created_to and created_from > created_to:
        raise ValidationFailed('"created_from" не может быть позже "created_to".')
    filters['created_from'] = day_bounds(created_from, False) if created_from else None
    filters['created_to'] = day_bounds(created_to, True) if created_to else None

    search = (query.get('search') or '').strip()
    if search:
        filters['search'] = search

    return filters


def list_bookings(query):
    page, page_size = parse_page_params(query)
    filters = _parse_filters(query)
    items = booking_repository.list_bookings(
        filters, page_size, (page - 1) * page_size, query.get('sort')
    )
    total = booking_repository.count_bookings(filters)
    return page_response(items, total, page, page_size)


def list_bookings_of_guest(guest_id, query):
    if not guest_repository.exists(guest_id):
        raise NotFound(f'Гость {guest_id} не найден.')
    query = query.copy()
    query['guest_id'] = guest_id
    return list_bookings(query)


def list_bookings_of_room(room_id, query):
    if not room_repository.exists(room_id):
        raise NotFound(f'Комната {room_id} не найдена.')
    query = query.copy()
    query['room_id'] = room_id
    return list_bookings(query)


def get_booking(booking_id):
    booking = booking_repository.get_booking(booking_id)
    if not booking:
        raise NotFound(f'Бронирование {booking_id} не найдено.')
    return booking


def _validate_payload(payload, booking_id=None):
    guest_id = as_int(payload.get('id_guest'), 'id_guest', 1)
    if not guest_repository.exists(guest_id):
        raise ValidationFailed(f'Гость {guest_id} не найден.')

    room_id = as_int(payload.get('id_room'), 'id_room', 1)
    room = room_repository.get_room(room_id)
    if not room:
        raise ValidationFailed(f'Комната {room_id} не найдена.')

    check_in = as_date(payload.get('check_in'), 'check_in')
    check_out = as_date(payload.get('check_out'), 'check_out')
    if check_out <= check_in:
        raise ValidationFailed('Дата выезда должна быть позже даты заезда.')

    status = one_of(payload.get('status') or 'pending', BOOKING_STATUSES, 'status')

    if status != 'cancelled':
        overlap = booking_repository.find_overlapping(room_id, check_in, check_out, booking_id)
        if overlap:
            raise Conflict(
                'Комната уже занята в выбранные даты.',
                {'conflicting_booking_id': overlap['id_booking']},
            )

    if payload.get('total_price') is not None:
        total_price = payload['total_price']
    else:
        nights = (check_out - check_in).days
        total_price = room['price_per_night'] * nights

    return {
        'id_guest': guest_id,
        'id_room': room_id,
        'check_in': check_in,
        'check_out': check_out,
        'status': status,
        'total_price': total_price,
    }


def create_booking(payload):
    data = _validate_payload(payload)
    return booking_repository.create_booking(data)


def update_booking(booking_id, payload):
    if not booking_repository.exists(booking_id):
        raise NotFound(f'Бронирование {booking_id} не найдено.')
    data = _validate_payload(payload, booking_id=booking_id)
    return booking_repository.update_booking(booking_id, data)


def delete_booking(booking_id):
    """
    Удаляет бронь вместе с её услугами и платежами.

    Каскад выполняется явно: доступ к данным идёт через SQL, а не через ORM,
    поэтому on_delete у моделей на уровне БД не срабатывает.
    """
    if not booking_repository.exists(booking_id):
        raise NotFound(f'Бронирование {booking_id} не найдено.')
    with transaction.atomic():
        booking_repository.delete_services_of_booking(booking_id)
        payment_repository.delete_payments_of_booking(booking_id)
        booking_repository.delete_booking(booking_id)


def list_services_of_booking(booking_id):
    if not booking_repository.exists(booking_id):
        raise NotFound(f'Бронирование {booking_id} не найдено.')
    items = booking_repository.list_services_of_booking(booking_id)
    return {'items': items, 'total': len(items)}


def add_service_to_booking(booking_id, payload):
    if not booking_repository.exists(booking_id):
        raise NotFound(f'Бронирование {booking_id} не найдено.')
    service_id = as_int(payload.get('id_service'), 'id_service', 1)
    if not service_repository.exists(service_id):
        raise ValidationFailed(f'Услуга {service_id} не найдена.')
    quantity = as_int(payload.get('quantity', 1), 'quantity', 1)
    try:
        return booking_repository.add_service_to_booking(booking_id, service_id, quantity)
    except IntegrityError as exc:
        raise Conflict('Не удалось добавить услугу к брони.', {'error': str(exc)})


def remove_service_from_booking(booking_id, service_id):
    deleted = booking_repository.remove_service_from_booking(booking_id, service_id)
    if not deleted:
        raise NotFound(f'Услуга {service_id} не найдена в брони {booking_id}.')
