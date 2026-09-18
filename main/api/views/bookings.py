"""Бронирования — основная сущность сервиса, включая услуги и платежи брони."""

from ...services import booking_service, payment_service
from ..http import endpoint, json_response, parse_body


@endpoint(['GET', 'POST'])
def bookings_collection(request):
    if request.method == 'GET':
        return json_response(booking_service.list_bookings(request.GET))
    return json_response(booking_service.create_booking(parse_body(request)), status=201)


@endpoint(['GET', 'PUT', 'DELETE'])
def booking_item(request, booking_id):
    booking_id = int(booking_id)
    if request.method == 'GET':
        return json_response(booking_service.get_booking(booking_id))
    if request.method == 'PUT':
        return json_response(booking_service.update_booking(booking_id, parse_body(request)))
    booking_service.delete_booking(booking_id)
    return json_response({'deleted': booking_id})


@endpoint(['GET', 'POST'])
def booking_services(request, booking_id):
    booking_id = int(booking_id)
    if request.method == 'GET':
        return json_response(booking_service.list_services_of_booking(booking_id))
    return json_response(
        booking_service.add_service_to_booking(booking_id, parse_body(request)), status=201
    )


@endpoint(['DELETE'])
def booking_service_item(request, booking_id, service_id):
    booking_service.remove_service_from_booking(int(booking_id), int(service_id))
    return json_response({'deleted': {'id_booking': int(booking_id), 'id_service': int(service_id)}})


@endpoint(['GET'])
def booking_payments(request, booking_id):
    return json_response(payment_service.list_payments_of_booking(int(booking_id), request.GET))
