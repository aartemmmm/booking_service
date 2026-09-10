"""Бизнес-логика по комнатам и типам комнат."""

from ..models import ROOM_STATUSES
from ..repositories import room_repository
from .errors import NotFound, ValidationFailed, integrity_guard
from .pagination import page_response, parse_page_params
from .validation import as_decimal, as_int, as_optional_int, as_str, one_of


def _parse_filters(query):
    filters = {}
    if query.get('status'):
        filters['status'] = one_of(query['status'], ROOM_STATUSES, 'status')
    filters['room_type_id'] = as_optional_int(query.get('room_type_id'), 'room_type_id', 1)
    filters['floor'] = as_optional_int(query.get('floor'), 'floor')
    search = (query.get('search') or '').strip()
    if search:
        filters['search'] = search
    return filters


def list_rooms(query):
    page, page_size = parse_page_params(query)
    filters = _parse_filters(query)
    items = room_repository.list_rooms(
        filters, page_size, (page - 1) * page_size, query.get('sort')
    )
    total = room_repository.count_rooms(filters)
    return page_response(items, total, page, page_size)


def get_room(room_id):
    room = room_repository.get_room(room_id)
    if not room:
        raise NotFound(f'Комната {room_id} не найдена.')
    return room


def _validate_room_payload(payload):
    type_id = as_int(payload.get('id_type'), 'id_type', 1)
    if not room_repository.room_type_exists(type_id):
        raise ValidationFailed(f'Тип комнаты {type_id} не найден.')
    return {
        'room_number': as_str(payload, 'room_number', max_length=20),
        'id_type': type_id,
        'floor': as_optional_int(payload.get('floor'), 'floor'),
        'status': one_of(payload.get('status') or 'available', ROOM_STATUSES, 'status'),
    }


def create_room(payload):
    data = _validate_room_payload(payload)
    with integrity_guard('Комната с таким номером уже существует.'):
        return room_repository.create_room(data)


def update_room(room_id, payload):
    if not room_repository.exists(room_id):
        raise NotFound(f'Комната {room_id} не найдена.')
    data = _validate_room_payload(payload)
    with integrity_guard('Комната с таким номером уже существует.'):
        return room_repository.update_room(room_id, data)


def delete_room(room_id):
    with integrity_guard('Комнату нельзя удалить: есть связанные бронирования.'):
        deleted = room_repository.delete_room(room_id)
    if not deleted:
        raise NotFound(f'Комната {room_id} не найдена.')


# ---------------------------------------------------------------- room types


def list_room_types(query):
    page, page_size = parse_page_params(query)
    filters = {}
    search = (query.get('search') or '').strip()
    if search:
        filters['search'] = search
    if query.get('price_max'):
        filters['price_max'] = as_decimal(query.get('price_max'), 'price_max', 0)
    items = room_repository.list_room_types(
        filters, page_size, (page - 1) * page_size, query.get('sort')
    )
    total = room_repository.count_room_types(filters)
    return page_response(items, total, page, page_size)


def get_room_type(type_id):
    room_type = room_repository.get_room_type(type_id)
    if not room_type:
        raise NotFound(f'Тип комнаты {type_id} не найден.')
    return room_type


def _validate_type_payload(payload):
    return {
        'name': as_str(payload, 'name', max_length=100),
        'description': as_str(payload, 'description', required_field=False),
        'price_per_night': as_decimal(payload.get('price_per_night'), 'price_per_night', 0),
    }


def create_room_type(payload):
    data = _validate_type_payload(payload)
    with integrity_guard('Тип комнаты с таким названием уже существует.'):
        return room_repository.create_room_type(data)


def update_room_type(type_id, payload):
    if not room_repository.room_type_exists(type_id):
        raise NotFound(f'Тип комнаты {type_id} не найден.')
    data = _validate_type_payload(payload)
    with integrity_guard('Тип комнаты с таким названием уже существует.'):
        return room_repository.update_room_type(type_id, data)


def delete_room_type(type_id):
    with integrity_guard('Тип комнаты нельзя удалить: есть связанные комнаты.'):
        deleted = room_repository.delete_room_type(type_id)
    if not deleted:
        raise NotFound(f'Тип комнаты {type_id} не найден.')
