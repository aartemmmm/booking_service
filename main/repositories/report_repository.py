"""Агрегирующие SQL-запросы для отчётов."""

from .base import build_where, query_all


def revenue_by_room_type(params):
    """
    Агрегирующий запрос: выручка и статистика бронирований по типам номеров.
    JOIN bookings -> rooms -> roomtypes + GROUP BY + COUNT/SUM/AVG/MIN/MAX.
    """
    conditions = []
    values = []
    if params.get('created_from'):
        conditions.append('b.created_at >= %s')
        values.append(params['created_from'])
    if params.get('created_to'):
        conditions.append('b.created_at <= %s')
        values.append(params['created_to'])
    if params.get('status'):
        conditions.append('b.status = %s')
        values.append(params['status'])

    sql = f"""
        SELECT rt.id_type,
               rt.name AS room_type,
               COUNT(b.id_booking)                       AS bookings_count,
               COALESCE(SUM(b.total_price), 0)           AS total_revenue,
               COALESCE(AVG(b.total_price), 0)           AS average_price,
               MIN(b.total_price)                        AS min_price,
               MAX(b.total_price)                        AS max_price,
               COALESCE(SUM(b.check_out - b.check_in), 0) AS total_nights
        FROM bookings b
        JOIN rooms r      ON r.id_room = b.id_room
        JOIN roomtypes rt ON rt.id_type = r.id_type
        {build_where(conditions)}
        GROUP BY rt.id_type, rt.name
        ORDER BY total_revenue DESC
    """
    return query_all(sql, values)


def top_guests(params, limit):
    """
    Агрегирующий запрос: самые ценные гости.
    JOIN guests -> bookings -> rooms -> roomtypes + GROUP BY + HAVING.
    """
    conditions = []
    values = []
    if params.get('created_from'):
        conditions.append('b.created_at >= %s')
        values.append(params['created_from'])
    if params.get('created_to'):
        conditions.append('b.created_at <= %s')
        values.append(params['created_to'])

    sql = f"""
        SELECT g.id_guest,
               g.last_name,
               g.first_name,
               g.email,
               COUNT(b.id_booking)             AS bookings_count,
               COALESCE(SUM(b.total_price), 0) AS total_spent,
               COALESCE(AVG(b.total_price), 0) AS average_check,
               MAX(b.check_out)                AS last_check_out
        FROM guests g
        JOIN bookings b   ON b.id_guest = g.id_guest
        JOIN rooms r      ON r.id_room = b.id_room
        JOIN roomtypes rt ON rt.id_type = r.id_type
        {build_where(conditions)}
        GROUP BY g.id_guest, g.last_name, g.first_name, g.email
        HAVING COUNT(b.id_booking) > 0
        ORDER BY total_spent DESC
        LIMIT %s
    """
    return query_all(sql, values + [limit])
