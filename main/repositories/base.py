"""
Единственное место, где приложение обращается к PostgreSQL.

Подключения (settings.DATABASES):
  PRIMARY ('default') — Primary: все записи и чтение по умолчанию;
  REPLICA ('replica') — Replica: только чтение, для read-сценариев,
                        которым допустимо небольшое отставание данных.

Функции чтения принимают параметр using и по умолчанию идут на Primary.
execute() всегда выполняется на Primary: Replica принимает только чтение.
"""

from django.db import connections

PRIMARY = 'default'
REPLICA = 'replica-1'


def _rows_to_dicts(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_all(sql, params=None, using=PRIMARY):
    """Вернуть все строки результата в виде списка словарей."""
    with connections[using].cursor() as cursor:
        cursor.execute(sql, params or [])
        return _rows_to_dicts(cursor)


def query_one(sql, params=None, using=PRIMARY):
    """Вернуть первую строку результата или None."""
    with connections[using].cursor() as cursor:
        cursor.execute(sql, params or [])
        rows = _rows_to_dicts(cursor)
    return rows[0] if rows else None


def scalar(sql, params=None, using=PRIMARY):
    """Вернуть первое поле первой строки (COUNT, SUM и т.п.)."""
    with connections[using].cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
    return row[0] if row else None


def execute(sql, params=None):
    """
    Выполнить INSERT/UPDATE/DELETE без RETURNING, вернуть число затронутых строк.

    Запись всегда идёт на Primary — единственный экземпляр, принимающий изменения.
    """
    with connections[PRIMARY].cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.rowcount


def ping(using=PRIMARY):
    """Проверка доступности БД для /health."""
    with connections[using].cursor() as cursor:
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
