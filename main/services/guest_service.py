"""Бизнес-логика по гостям отеля."""

from ..repositories import guest_repository
from .errors import NotFound, integrity_guard
from .pagination import page_response, parse_page_params
from .validation import as_str


def _parse_filters(query):
    filters = {}
    search = (query.get('search') or '').strip()
    if search:
        filters['search'] = search
    email = (query.get('email') or '').strip()
    if email:
        filters['email'] = email
    return filters


def list_guests(query):
    page, page_size = parse_page_params(query)
    filters = _parse_filters(query)
    items = guest_repository.list_guests(
        filters, page_size, (page - 1) * page_size, query.get('sort')
    )
    total = guest_repository.count_guests(filters)
    return page_response(items, total, page, page_size)


def get_guest(guest_id):
    guest = guest_repository.get_guest(guest_id)
    if not guest:
        raise NotFound(f'Гость {guest_id} не найден.')
    return guest


def _validate_payload(payload):
    return {
        'last_name': as_str(payload, 'last_name', max_length=100),
        'first_name': as_str(payload, 'first_name', max_length=100),
        'middle_name': as_str(payload, 'middle_name', required_field=False, max_length=100),
        'phone': as_str(payload, 'phone', required_field=False, max_length=32),
        'email': as_str(payload, 'email', required_field=False, max_length=255),
        'passport_number': as_str(payload, 'passport_number', required_field=False, max_length=32),
    }


def create_guest(payload):
    data = _validate_payload(payload)
    with integrity_guard('Гость с такими телефоном, email или паспортом уже существует.'):
        return guest_repository.create_guest(data)


def update_guest(guest_id, payload):
    if not guest_repository.exists(guest_id):
        raise NotFound(f'Гость {guest_id} не найден.')
    data = _validate_payload(payload)
    with integrity_guard('Гость с такими телефоном, email или паспортом уже существует.'):
        return guest_repository.update_guest(guest_id, data)


def delete_guest(guest_id):
    with integrity_guard('Гостя нельзя удалить: есть связанные записи.'):
        deleted = guest_repository.delete_guest(guest_id)
    if not deleted:
        raise NotFound(f'Гость {guest_id} не найден.')
