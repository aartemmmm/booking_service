"""Утилиты HTTP-слоя: JSON-ответы, разбор тела запроса, обработка ошибок."""

import json
from functools import wraps

from django.http import JsonResponse

from ..services.errors import ServiceError, ValidationFailed


def json_response(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def error_response(message, status, details=None):
    body = {'error': message}
    if details:
        body['details'] = details
    return json_response(body, status=status)


def parse_body(request):
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationFailed('Тело запроса должно быть корректным JSON.')
    if not isinstance(payload, dict):
        raise ValidationFailed('Тело запроса должно быть JSON-объектом.')
    return payload


def endpoint(methods):
    """
    Оборачивает handler: проверяет HTTP-метод и превращает доменные ошибки
    сервисного слоя в JSON-ответы с нужным статусом.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return error_response(
                    f'Метод {request.method} не поддерживается.',
                    405,
                    {'allowed': list(methods)},
                )
            try:
                return view(request, *args, **kwargs)
            except ServiceError as exc:
                return error_response(exc.message, exc.status_code, exc.details)

        return wrapper

    return decorator
