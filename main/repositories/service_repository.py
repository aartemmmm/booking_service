"""SQL-запросы к таблице services."""

from .base import build_where, execute, order_by_clause, query_all, query_one, scalar

SORT_FIELDS = {'id': 'id_service', 'name': 'name', 'price': 'price'}
DEFAULT_ORDER = 'id_service ASC'
COLUMNS = 'id_service, name, description, price'


def _filters(params):
    conditions = []
    values = []
    if params.get('search'):
        conditions.append('name ILIKE %s')
        values.append(f"%{params['search']}%")
    if params.get('price_max'):
        conditions.append('price <= %s')
        values.append(params['price_max'])
    return conditions, values


def list_services(params, limit, offset, sort=None):
    conditions, values = _filters(params)
    sql = f"""
        SELECT {COLUMNS}
        FROM services
        {build_where(conditions)}
        ORDER BY {order_by_clause(sort, SORT_FIELDS, DEFAULT_ORDER)}
        LIMIT %s OFFSET %s
    """
    return query_all(sql, values + [limit, offset])


def count_services(params):
    conditions, values = _filters(params)
    return scalar(f'SELECT COUNT(*) FROM services {build_where(conditions)}', values) or 0


def get_service(service_id):
    return query_one(f'SELECT {COLUMNS} FROM services WHERE id_service = %s', [service_id])


def create_service(data):
    sql = f"""
        INSERT INTO services (name, description, price)
        VALUES (%s, %s, %s)
        RETURNING {COLUMNS}
    """
    return query_one(sql, [data['name'], data.get('description'), data['price']])


def update_service(service_id, data):
    sql = f"""
        UPDATE services
        SET name = %s, description = %s, price = %s
        WHERE id_service = %s
        RETURNING {COLUMNS}
    """
    return query_one(sql, [data['name'], data.get('description'), data['price'], service_id])


def delete_service(service_id):
    return execute('DELETE FROM services WHERE id_service = %s', [service_id])


def exists(service_id):
    return scalar('SELECT 1 FROM services WHERE id_service = %s', [service_id]) is not None
