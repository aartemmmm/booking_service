"""Разбор и проверка входных данных запроса."""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .errors import ValidationFailed


def as_str(data, field, required_field=True, max_length=None, default=None):
    if field not in data or data.get(field) is None:
        if required_field:
            raise ValidationFailed(f'Поле "{field}" обязательно.')
        return default
    value = str(data[field]).strip()
    if required_field and not value:
        raise ValidationFailed(f'Поле "{field}" не может быть пустым.')
    if not value:
        return default
    if max_length and len(value) > max_length:
        raise ValidationFailed(f'Поле "{field}" длиннее {max_length} символов.')
    return value


def as_int(value, field, minimum=None):
    if value is None:
        raise ValidationFailed(f'Поле "{field}" обязательно.')
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValidationFailed(f'Поле "{field}" должно быть целым числом.')
    if minimum is not None and result < minimum:
        raise ValidationFailed(f'Поле "{field}" должно быть не меньше {minimum}.')
    return result


def as_optional_int(value, field, minimum=None):
    if value is None or value == '':
        return None
    return as_int(value, field, minimum)


def as_decimal(value, field, minimum=None):
    if value is None or value == '':
        raise ValidationFailed(f'Поле "{field}" обязательно.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationFailed(f'Поле "{field}" должно быть числом.')
    if minimum is not None and result < Decimal(str(minimum)):
        raise ValidationFailed(f'Поле "{field}" должно быть не меньше {minimum}.')
    return result


def as_date(value, field):
    if isinstance(value, date):
        return value
    if not value:
        raise ValidationFailed(f'Поле "{field}" обязательно.')
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        raise ValidationFailed(f'Поле "{field}" должно быть датой в формате YYYY-MM-DD.')


def as_optional_date(value, field):
    if value is None or value == '':
        return None
    return as_date(value, field)


def one_of(value, allowed, field):
    if value not in allowed:
        raise ValidationFailed(
            f'Недопустимое значение поля "{field}".',
            {'allowed': list(allowed)},
        )
    return value


def day_bounds(value, end_of_day):
    """Дата из query-параметра -> момент времени для сравнения с created_at."""
    moment = datetime.combine(value, time.max if end_of_day else time.min)
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment
