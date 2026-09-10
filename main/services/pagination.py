"""Пагинация для списковых endpoint'ов."""

from django.conf import settings

from .errors import ValidationFailed


def parse_page_params(query):
    page = query.get('page', 1)
    page_size = query.get('page_size', settings.API_DEFAULT_PAGE_SIZE)
    try:
        page = int(page)
        page_size = int(page_size)
    except (TypeError, ValueError):
        raise ValidationFailed('Параметры "page" и "page_size" должны быть целыми числами.')
    if page < 1:
        raise ValidationFailed('Параметр "page" должен быть больше 0.')
    if page_size < 1 or page_size > settings.API_MAX_PAGE_SIZE:
        raise ValidationFailed(
            f'Параметр "page_size" должен быть в диапазоне 1..{settings.API_MAX_PAGE_SIZE}.'
        )
    return page, page_size


def page_response(items, total, page, page_size):
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        'items': items,
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': total_pages,
    }
