"""Бизнес-логика по платежам."""

from ..models import PAYMENT_METHODS, PAYMENT_STATUSES
from ..repositories import booking_repository, payment_repository
from .errors import NotFound, ValidationFailed, integrity_guard
from .pagination import page_response, parse_page_params
from .validation import as_date, as_decimal, as_int, as_optional_date, as_optional_int, one_of


def _parse_filters(query):
    filters = {}
    if query.get('status'):
        filters['status'] = one_of(query['status'], PAYMENT_STATUSES, 'status')
    if query.get('method'):
        filters['method'] = one_of(query['method'], PAYMENT_METHODS, 'method')
    filters['booking_id'] = as_optional_int(query.get('booking_id'), 'booking_id', 1)
    date_from = as_optional_date(query.get('date_from'), 'date_from')
    date_to = as_optional_date(query.get('date_to'), 'date_to')
    if date_from and date_to and date_from > date_to:
        raise ValidationFailed('"date_from" не может быть позже "date_to".')
    filters['date_from'] = date_from
    filters['date_to'] = date_to
    return filters


def list_payments(query):
    page, page_size = parse_page_params(query)
    filters = _parse_filters(query)
    items = payment_repository.list_payments(
        filters, page_size, (page - 1) * page_size, query.get('sort')
    )
    total = payment_repository.count_payments(filters)
    return page_response(items, total, page, page_size)


def list_payments_of_booking(booking_id, query):
    if not booking_repository.exists(booking_id):
        raise NotFound(f'Бронирование {booking_id} не найдено.')
    query = query.copy()
    query['booking_id'] = booking_id
    return list_payments(query)


def get_payment(payment_id):
    payment = payment_repository.get_payment(payment_id)
    if not payment:
        raise NotFound(f'Платёж {payment_id} не найден.')
    return payment


def _validate_payload(payload):
    booking_id = as_int(payload.get('id_booking'), 'id_booking', 1)
    if not booking_repository.exists(booking_id):
        raise ValidationFailed(f'Бронирование {booking_id} не найдено.')
    return {
        'id_booking': booking_id,
        'payment_date': as_date(payload.get('payment_date'), 'payment_date'),
        'amount': as_decimal(payload.get('amount'), 'amount', 0),
        'method': one_of(payload.get('method'), PAYMENT_METHODS, 'method'),
        'status': one_of(payload.get('status') or 'pending', PAYMENT_STATUSES, 'status'),
    }


def create_payment(payload):
    data = _validate_payload(payload)
    with integrity_guard('Не удалось сохранить платёж.'):
        return payment_repository.create_payment(data)


def update_payment(payment_id, payload):
    if not payment_repository.get_payment(payment_id):
        raise NotFound(f'Платёж {payment_id} не найден.')
    data = _validate_payload(payload)
    with integrity_guard('Не удалось сохранить платёж.'):
        return payment_repository.update_payment(payment_id, data)


def delete_payment(payment_id):
    deleted = payment_repository.delete_payment(payment_id)
    if not deleted:
        raise NotFound(f'Платёж {payment_id} не найден.')
