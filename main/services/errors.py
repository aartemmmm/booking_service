"""Доменные ошибки сервисного слоя. API-слой превращает их в HTTP-ответы."""

from contextlib import contextmanager

from django.db import IntegrityError


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationFailed(ServiceError):
    status_code = 400


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


@contextmanager
def integrity_guard(message):
    """Ошибки уникальности и внешних ключей PostgreSQL -> ответ 409."""
    try:
        yield
    except IntegrityError as exc:
        raise Conflict(message, {'error': str(exc).strip().splitlines()[0]})
