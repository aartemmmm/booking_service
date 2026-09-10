"""SQL-запросы к таблицам rooms и roomtypes."""

from .base import build_where, execute, order_by_clause, query_all, query_one, scalar

SORT_FIELDS = {
    'id': 'r.id_room',
    'room_number': 'r.room_number',
    'floor': 'r.floor',
    'price': 'rt.price_per_night',
}
DEFAULT_ORDER = 'r.id_room ASC'

ROOM_SELECT = """
    SELECT r.id_room, r.room_number, r.floor, r.status,
           rt.id_type, rt.name AS room_type, rt.price_per_night
    FROM rooms r
    JOIN roomtypes rt ON rt.id_type = r.id_type
"""


def _filters(params):
    conditions = []
    values = []
    if params.get('status'):
        conditions.append('r.status = %s')
        values.append(params['status'])
    if params.get('room_type_id'):
        conditions.append('r.id_type = %s')
        values.append(params['room_type_id'])
    if params.get('floor'):
        conditions.append('r.floor = %s')
        values.append(params['floor'])
    if params.get('search'):
        conditions.append('(r.room_number ILIKE %s OR rt.name ILIKE %s)')
        pattern = f"%{params['search']}%"
        values.extend([pattern, pattern])
    return conditions, values


def list_rooms(params, limit, offset, sort=None):
    conditions, values = _filters(params)
    sql = f"""
        {ROOM_SELECT}
        {build_where(conditions)}
        ORDER BY {order_by_clause(sort, SORT_FIELDS, DEFAULT_ORDER)}
        LIMIT %s OFFSET %s
    """
    return query_all(sql, values + [limit, offset])


def count_rooms(params):
    conditions, values = _filters(params)
    sql = f"""
        SELECT COUNT(*)
        FROM rooms r
        JOIN roomtypes rt ON rt.id_type = r.id_type
        {build_where(conditions)}
    """
    return scalar(sql, values) or 0


def get_room(room_id):
    return query_one(f'{ROOM_SELECT} WHERE r.id_room = %s', [room_id])


def create_room(data):
    sql = """
        INSERT INTO rooms (room_number, id_type, floor, status)
        VALUES (%s, %s, %s, %s)
        RETURNING id_room, room_number, id_type, floor, status
    """
    return query_one(
        sql,
        [data['room_number'], data['id_type'], data.get('floor'), data['status']],
    )


def update_room(room_id, data):
    sql = """
        UPDATE rooms
        SET room_number = %s, id_type = %s, floor = %s, status = %s
        WHERE id_room = %s
        RETURNING id_room, room_number, id_type, floor, status
    """
    return query_one(
        sql,
        [data['room_number'], data['id_type'], data.get('floor'), data['status'], room_id],
    )


def delete_room(room_id):
    return execute('DELETE FROM rooms WHERE id_room = %s', [room_id])


def exists(room_id):
    return scalar('SELECT 1 FROM rooms WHERE id_room = %s', [room_id]) is not None


# ---------------------------------------------------------------- room types

TYPE_SORT_FIELDS = {
    'id': 'id_type',
    'name': 'name',
    'price': 'price_per_night',
}
TYPE_DEFAULT_ORDER = 'id_type ASC'


def _type_filters(params):
    conditions = []
    values = []
    if params.get('search'):
        conditions.append('name ILIKE %s')
        values.append(f"%{params['search']}%")
    if params.get('price_max'):
        conditions.append('price_per_night <= %s')
        values.append(params['price_max'])
    return conditions, values


def list_room_types(params, limit, offset, sort=None):
    conditions, values = _type_filters(params)
    sql = f"""
        SELECT id_type, name, description, price_per_night
        FROM roomtypes
        {build_where(conditions)}
        ORDER BY {order_by_clause(sort, TYPE_SORT_FIELDS, TYPE_DEFAULT_ORDER)}
        LIMIT %s OFFSET %s
    """
    return query_all(sql, values + [limit, offset])


def count_room_types(params):
    conditions, values = _type_filters(params)
    return scalar(f'SELECT COUNT(*) FROM roomtypes {build_where(conditions)}', values) or 0


def get_room_type(type_id):
    return query_one(
        'SELECT id_type, name, description, price_per_night FROM roomtypes WHERE id_type = %s',
        [type_id],
    )


def create_room_type(data):
    sql = """
        INSERT INTO roomtypes (name, description, price_per_night)
        VALUES (%s, %s, %s)
        RETURNING id_type, name, description, price_per_night
    """
    return query_one(sql, [data['name'], data.get('description'), data['price_per_night']])


def update_room_type(type_id, data):
    sql = """
        UPDATE roomtypes
        SET name = %s, description = %s, price_per_night = %s
        WHERE id_type = %s
        RETURNING id_type, name, description, price_per_night
    """
    return query_one(
        sql, [data['name'], data.get('description'), data['price_per_night'], type_id]
    )


def delete_room_type(type_id):
    return execute('DELETE FROM roomtypes WHERE id_type = %s', [type_id])


def room_type_exists(type_id):
    return scalar('SELECT 1 FROM roomtypes WHERE id_type = %s', [type_id]) is not None
