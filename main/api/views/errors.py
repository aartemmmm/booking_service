"""Обработчики ошибок Django (handler404 / handler500 в booking_service/urls.py)."""

from ..http import error_response


def not_found(request, exception=None):
    return error_response('Ресурс не найден.', 404)


def server_error(request):
    return error_response('Внутренняя ошибка сервиса.', 500)
