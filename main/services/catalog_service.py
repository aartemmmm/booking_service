"""Бизнес-логика по каталогу дополнительных услуг отеля."""

from ..repositories import service_repository
from .errors import NotFound, integrity_guard
from .pagination import page_response, parse_page_params
from .validation import as_decimal, as_str


def _parse_filters(query):
    filters = {}
    search = (query.get('search') or '').strip()
    if search:
        filters['search'] = search
    if query.get('price_max'):
        filters['price_max'] = as_decimal(query.get('price_max'), 'price_max', 0)
    return filters


def list_services(query):
    page, page_size = parse_page_params(query)
    filters = _parse_filters(query)
    items = service_repository.list_services(
        filters, page_size, (page - 1) * page_size, query.get('sort')
    )
    total = service_repository.count_services(filters)
    return page_response(items, total, page, page_size)


def get_service(service_id):
    service = service_repository.get_service(service_id)
    if not service:
        raise NotFound(f'Услуга {service_id} не найдена.')
    return service


def _validate_payload(payload):
    return {
        'name': as_str(payload, 'name', max_length=150),
        'description': as_str(payload, 'description', required_field=False),
        'price': as_decimal(payload.get('price'), 'price', 0),
    }


def create_service(payload):
    data = _validate_payload(payload)
    with integrity_guard('Услуга с таким названием уже существует.'):
        return service_repository.create_service(data)


def update_service(service_id, payload):
    if not service_repository.exists(service_id):
        raise NotFound(f'Услуга {service_id} не найдена.')
    data = _validate_payload(payload)
    with integrity_guard('Услуга с таким названием уже существует.'):
        return service_repository.update_service(service_id, data)


def delete_service(service_id):
    with integrity_guard('Услугу нельзя удалить: она используется в бронированиях.'):
        deleted = service_repository.delete_service(service_id)
    if not deleted:
        raise NotFound(f'Услуга {service_id} не найдена.')
