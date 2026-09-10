"""Проверка работоспособности сервиса и его подключения к PostgreSQL."""

from ..repositories import base


def check():
    try:
        base.ping()
        database_ok = True
        error = None
    except Exception as exc:
        database_ok = False
        error = str(exc).strip().splitlines()[0]

    result = {
        'status': 'ok' if database_ok else 'error',
        'database': 'ok' if database_ok else 'unavailable',
    }
    if error:
        result['error'] = error
    return result, database_ok
