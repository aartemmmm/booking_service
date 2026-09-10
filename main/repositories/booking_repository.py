"""SQL-запросы к основной растущей сущности bookings."""

from .base import build_where, execute, order_by_clause, query_all, query_one, scalar

# Поля, по которым разрешена сортировка (?sort=created_at / ?sort=-created_at)
SORT_FIELDS = {
    'id': 'b.id_booking',
    'created_at': 'b.created_at',
    'check_in': 'b.check_in',
    'check_out': 'b.check_out',
    'total_price': 'b.total_price',
}

DEFAULT_ORDER = 'b.created_at DESC'

# Нетривиальный JOIN-запрос №1: бронирования вместе с гостем, комнатой и типом комнаты
LIST_SELECT = """
    SELECT b.id_booking,
           b.check_in,
           b.check_out,
           b.total_price,
           b.status,
           b.created_at,
           b.updated_at,
           g.id_guest,
           g.last_name  AS guest_last_name,
           g.first_name AS guest_first_name,
           g.email      AS guest_email,
           r.id_room,
           r.room_number,
           r.floor,
           rt.id_type,
           rt.name           AS room_type,
           rt.price_per_night
    FROM bookings b
    JOIN guests g    ON g.id_guest = b.id_guest
    JOIN rooms r     ON r.id_room = b.id_room
    JOIN roomtypes rt ON rt.id_type = r.id_type
"""


def _filters(params):
    """Собрать условия WHERE и список значений из параметров запроса."""
    conditions = []
    values = []

    if params.get('status'):
        conditions.append('b.status = %s')
        values.append(params['status'])

    if params.get('guest_id'):
        conditions.append('b.id_guest = %s')
        values.append(params['guest_id'])

    if params.get('room_id'):
        conditions.append('b.id_room = %s')
        values.append(params['room_id'])

    if params.get('room_type_id'):
        conditions.append('rt.id_type = %s')
        values.append(params['room_type_id'])

    if params.get('check_in_from'):
        conditions.append('b.check_in >= %s')
        values.append(params['check_in_from'])

    if params.get('check_in_to'):
        conditions.append('b.check_in <= %s')
        values.append(params['check_in_to'])

    # Диапазон по времени создания записи
    if params.get('created_from'):
        conditions.append('b.created_at >= %s')
        values.append(params['created_from'])

    if params.get('created_to'):
        conditions.append('b.created_at <= %s')
        values.append(params['created_to'])

    # Поиск по фамилии/имени гостя и номеру комнаты
    if params.get('search'):
        conditions.append(
            '(g.last_name ILIKE %s OR g.first_name ILIKE %s OR r.room_number ILIKE %s)'
        )
        pattern = f"%{params['search']}%"
        values.extend([pattern, pattern, pattern])

    return conditions, values


def list_bookings(params, limit, offset, sort=None):
    conditions, values = _filters(params)
    sql = f"""
        {LIST_SELECT}
        {build_where(conditions)}
        ORDER BY {order_by_clause(sort, SORT_FIELDS, DEFAULT_ORDER)}
        LIMIT %s OFFSET %s
    """
    return query_all(sql, values + [limit, offset])


def count_bookings(params):
    conditions, values = _filters(params)
    sql = f"""
        SELECT COUNT(*)
        FROM bookings b
        JOIN guests g     ON g.id_guest = b.id_guest
        JOIN rooms r      ON r.id_room = b.id_room
        JOIN roomtypes rt ON rt.id_type = r.id_type
        {build_where(conditions)}
    """
    return scalar(sql, values) or 0


def get_booking(booking_id):
    """
    Нетривиальный JOIN-запрос №2: карточка брони с гостем, комнатой, типом комнаты
    и агрегированной суммой успешных платежей (LEFT JOIN + GROUP BY).
    """
    sql = """
        SELECT b.id_booking,
               b.check_in,
               b.check_out,
               b.total_price,
               b.status,
               b.created_at,
               b.updated_at,
               g.id_guest,
               g.last_name  AS guest_last_name,
               g.first_name AS guest_first_name,
               g.email      AS guest_email,
               g.phone      AS guest_phone,
               r.id_room,
               r.room_number,
               r.floor,
               rt.id_type,
               rt.name AS room_type,
               rt.price_per_night,
               COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'success'), 0) AS paid_amount,
               COUNT(p.id_payment) AS payments_count
        FROM bookings b
        JOIN guests g     ON g.id_guest = b.id_guest
        JOIN rooms r      ON r.id_room = b.id_room
        JOIN roomtypes rt ON rt.id_type = r.id_type
        LEFT JOIN payments p ON p.id_booking = b.id_booking
        WHERE b.id_booking = %s
        GROUP BY b.id_booking, g.id_guest, r.id_room, rt.id_type
    """
    return query_one(sql, [booking_id])


def create_booking(data):
    sql = """
        INSERT INTO bookings (id_guest, id_room, check_in, check_out, total_price, status,
                              created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING id_booking, id_guest, id_room, check_in, check_out, total_price, status,
                  created_at, updated_at
    """
    return query_one(
        sql,
        [
            data['id_guest'],
            data['id_room'],
            data['check_in'],
            data['check_out'],
            data['total_price'],
            data['status'],
        ],
    )


def update_booking(booking_id, data):
    sql = """
        UPDATE bookings
        SET id_guest = %s,
            id_room = %s,
            check_in = %s,
            check_out = %s,
            total_price = %s,
            status = %s,
            updated_at = NOW()
        WHERE id_booking = %s
        RETURNING id_booking, id_guest, id_room, check_in, check_out, total_price, status,
                  created_at, updated_at
    """
    return query_one(
        sql,
        [
            data['id_guest'],
            data['id_room'],
            data['check_in'],
            data['check_out'],
            data['total_price'],
            data['status'],
            booking_id,
        ],
    )


def delete_booking(booking_id):
    return execute('DELETE FROM bookings WHERE id_booking = %s', [booking_id])


def delete_services_of_booking(booking_id):
    return execute('DELETE FROM bookingservices WHERE id_booking = %s', [booking_id])


def exists(booking_id):
    return scalar('SELECT 1 FROM bookings WHERE id_booking = %s', [booking_id]) is not None


def find_overlapping(room_id, check_in, check_out, exclude_id=None):
    """Проверка пересечения дат в одной комнате."""
    conditions = [
        'b.id_room = %s',
        'b.status <> %s',
        'b.check_in < %s',
        'b.check_out > %s',
    ]
    values = [room_id, 'cancelled', check_out, check_in]
    if exclude_id:
        conditions.append('b.id_booking <> %s')
        values.append(exclude_id)

    sql = f"""
        SELECT b.id_booking, b.check_in, b.check_out
        FROM bookings b
        {build_where(conditions)}
        LIMIT 1
    """
    return query_one(sql, values)


def list_services_of_booking(booking_id):
    """
    Нетривиальный JOIN-запрос №3: услуги конкретной брони
    (bookings -> bookingservices -> services) со стоимостью позиции.
    """
    sql = """
        SELECT s.id_service,
               s.name,
               s.price,
               bs.quantity,
               (bs.quantity * s.price) AS line_total,
               b.id_booking,
               b.status AS booking_status
        FROM bookingservices bs
        JOIN services s ON s.id_service = bs.id_service
        JOIN bookings b ON b.id_booking = bs.id_booking
        WHERE bs.id_booking = %s
        ORDER BY s.name
    """
    return query_all(sql, [booking_id])


def add_service_to_booking(booking_id, service_id, quantity):
    sql = """
        INSERT INTO bookingservices (id_booking, id_service, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (id_booking, id_service)
        DO UPDATE SET quantity = EXCLUDED.quantity
        RETURNING id_booking, id_service, quantity
    """
    return query_one(sql, [booking_id, service_id, quantity])


def remove_service_from_booking(booking_id, service_id):
    return execute(
        'DELETE FROM bookingservices WHERE id_booking = %s AND id_service = %s',
        [booking_id, service_id],
    )
