"""SQL-запросы к таблице payments."""

from .base import build_where, execute, order_by_clause, query_all, query_one, scalar

SORT_FIELDS = {
    'id': 'p.id_payment',
    'payment_date': 'p.payment_date',
    'amount': 'p.amount',
    'created_at': 'p.created_at',
}
DEFAULT_ORDER = 'p.id_payment DESC'

PAYMENT_SELECT = """
    SELECT p.id_payment, p.id_booking, p.payment_date, p.amount, p.method, p.status,
           p.created_at,
           g.id_guest, g.last_name AS guest_last_name, g.first_name AS guest_first_name
    FROM payments p
    JOIN bookings b ON b.id_booking = p.id_booking
    JOIN guests g   ON g.id_guest = b.id_guest
"""


def _filters(params):
    conditions = []
    values = []
    if params.get('status'):
        conditions.append('p.status = %s')
        values.append(params['status'])
    if params.get('method'):
        conditions.append('p.method = %s')
        values.append(params['method'])
    if params.get('booking_id'):
        conditions.append('p.id_booking = %s')
        values.append(params['booking_id'])
    if params.get('date_from'):
        conditions.append('p.payment_date >= %s')
        values.append(params['date_from'])
    if params.get('date_to'):
        conditions.append('p.payment_date <= %s')
        values.append(params['date_to'])
    return conditions, values


def list_payments(params, limit, offset, sort=None):
    conditions, values = _filters(params)
    sql = f"""
        {PAYMENT_SELECT}
        {build_where(conditions)}
        ORDER BY {order_by_clause(sort, SORT_FIELDS, DEFAULT_ORDER)}
        LIMIT %s OFFSET %s
    """
    return query_all(sql, values + [limit, offset])


def count_payments(params):
    conditions, values = _filters(params)
    sql = f"""
        SELECT COUNT(*)
        FROM payments p
        JOIN bookings b ON b.id_booking = p.id_booking
        JOIN guests g   ON g.id_guest = b.id_guest
        {build_where(conditions)}
    """
    return scalar(sql, values) or 0


def get_payment(payment_id):
    return query_one(f'{PAYMENT_SELECT} WHERE p.id_payment = %s', [payment_id])


def create_payment(data):
    sql = """
        INSERT INTO payments (id_booking, payment_date, amount, method, status, created_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        RETURNING id_payment, id_booking, payment_date, amount, method, status, created_at
    """
    return query_one(
        sql,
        [
            data['id_booking'],
            data['payment_date'],
            data['amount'],
            data['method'],
            data['status'],
        ],
    )


def update_payment(payment_id, data):
    sql = """
        UPDATE payments
        SET id_booking = %s, payment_date = %s, amount = %s, method = %s, status = %s
        WHERE id_payment = %s
        RETURNING id_payment, id_booking, payment_date, amount, method, status, created_at
    """
    return query_one(
        sql,
        [
            data['id_booking'],
            data['payment_date'],
            data['amount'],
            data['method'],
            data['status'],
            payment_id,
        ],
    )


def delete_payment(payment_id):
    return execute('DELETE FROM payments WHERE id_payment = %s', [payment_id])


def delete_payments_of_booking(booking_id):
    return execute('DELETE FROM payments WHERE id_booking = %s', [booking_id])
