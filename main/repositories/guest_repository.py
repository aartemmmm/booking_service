"""SQL-запросы к таблице guests."""

from .base import build_where, execute, order_by_clause, query_all, query_one, scalar

SORT_FIELDS = {
    'id': 'g.id_guest',
    'last_name': 'g.last_name',
    'created_at': 'g.created_at',
}
DEFAULT_ORDER = 'g.id_guest ASC'

COLUMNS = """
    g.id_guest, g.last_name, g.first_name, g.middle_name,
    g.phone, g.email, g.passport_number, g.created_at
"""


def _filters(params):
    conditions = []
    values = []
    if params.get('search'):
        conditions.append(
            '(g.last_name ILIKE %s OR g.first_name ILIKE %s OR g.email ILIKE %s)'
        )
        pattern = f"%{params['search']}%"
        values.extend([pattern, pattern, pattern])
    if params.get('email'):
        conditions.append('g.email = %s')
        values.append(params['email'])
    return conditions, values


def list_guests(params, limit, offset, sort=None):
    conditions, values = _filters(params)
    sql = f"""
        SELECT {COLUMNS}
        FROM guests g
        {build_where(conditions)}
        ORDER BY {order_by_clause(sort, SORT_FIELDS, DEFAULT_ORDER)}
        LIMIT %s OFFSET %s
    """
    return query_all(sql, values + [limit, offset], using='replica-2')


def count_guests(params):
    conditions, values = _filters(params)
    sql = f'SELECT COUNT(*) FROM guests g {build_where(conditions)}'
    return scalar(sql, values) or 0


def get_guest(guest_id):
    return query_one(f'SELECT {COLUMNS} FROM guests g WHERE g.id_guest = %s', [guest_id])


def create_guest(data):
    sql = """
        INSERT INTO guests (last_name, first_name, middle_name, phone, email,
                            passport_number, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        RETURNING id_guest, last_name, first_name, middle_name, phone, email,
                  passport_number, created_at
    """
    return query_one(
        sql,
        [
            data['last_name'],
            data['first_name'],
            data.get('middle_name'),
            data.get('phone'),
            data.get('email'),
            data.get('passport_number'),
        ],
    )


def update_guest(guest_id, data):
    sql = """
        UPDATE guests
        SET last_name = %s,
            first_name = %s,
            middle_name = %s,
            phone = %s,
            email = %s,
            passport_number = %s
        WHERE id_guest = %s
        RETURNING id_guest, last_name, first_name, middle_name, phone, email,
                  passport_number, created_at
    """
    return query_one(
        sql,
        [
            data['last_name'],
            data['first_name'],
            data.get('middle_name'),
            data.get('phone'),
            data.get('email'),
            data.get('passport_number'),
            guest_id,
        ],
    )


def delete_guest(guest_id):
    return execute('DELETE FROM guests WHERE id_guest = %s', [guest_id])


def exists(guest_id):
    return scalar('SELECT 1 FROM guests WHERE id_guest = %s', [guest_id]) is not None
