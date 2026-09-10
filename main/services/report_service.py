"""Отчёты на агрегирующих SQL-запросах."""

from ..models import BOOKING_STATUSES
from ..repositories import report_repository
from .errors import ValidationFailed
from .validation import as_optional_date, as_optional_int, day_bounds, one_of


def _period(query):
    created_from = as_optional_date(query.get('created_from'), 'created_from')
    created_to = as_optional_date(query.get('created_to'), 'created_to')
    if created_from and created_to and created_from > created_to:
        raise ValidationFailed('"created_from" не может быть позже "created_to".')
    return {
        'created_from': day_bounds(created_from, False) if created_from else None,
        'created_to': day_bounds(created_to, True) if created_to else None,
    }


def revenue_by_room_type(query):
    params = _period(query)
    if query.get('status'):
        params['status'] = one_of(query['status'], BOOKING_STATUSES, 'status')
    rows = report_repository.revenue_by_room_type(params)
    return {
        'items': rows,
        'total_revenue': sum(row['total_revenue'] for row in rows),
        'total_bookings': sum(row['bookings_count'] for row in rows),
    }


def top_guests(query):
    params = _period(query)
    limit = as_optional_int(query.get('limit'), 'limit', 1) or 10
    rows = report_repository.top_guests(params, min(limit, 100))
    return {'items': rows, 'total': len(rows)}
