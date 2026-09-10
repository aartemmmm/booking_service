"""
Единственное место, где приложение обращается к PostgreSQL.

Все репозитории выполняют SQL через соединение Django (settings.DATABASES['default']).
"""

from django.db import connection


def _rows_to_dicts(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_all(sql, params=None):
    """Вернуть все строки результата в виде списка словарей."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return _rows_to_dicts(cursor)


def query_one(sql, params=None):
    """Вернуть первую строку результата или None."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        rows = _rows_to_dicts(cursor)
    return rows[0] if rows else None


def scalar(sql, params=None):
    """Вернуть первое поле первой строки (COUNT, SUM и т.п.)."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
    return row[0] if row else None


def execute(sql, params=None):
    """Выполнить INSERT/UPDATE/DELETE без RETURNING, вернуть число затронутых строк."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.rowcount


def ping():
    """Проверка доступности БД для /health."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()
    return True


def build_where(conditions):
    """Собрать блок WHERE из списка непустых условий."""
    if not conditions:
        return ''
    return 'WHERE ' + ' AND '.join(conditions)


def order_by_clause(sort, allowed, default):
    """
    Преобразовать параметр вида ?sort=-created_at в безопасный ORDER BY.

    Имя колонки берётся только из белого списка allowed, поэтому подстановка в SQL
    безопасна и SQL-инъекция невозможна.
    """
    if not sort:
        return default
    direction = 'ASC'
    field = sort
    if sort.startswith('-'):
        direction = 'DESC'
        field = sort[1:]
    column = allowed.get(field)
    if not column:
        return default
    return f'{column} {direction}'
