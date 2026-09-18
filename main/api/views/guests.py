"""Гости и их бронирования."""

from ...services import booking_service, guest_service
from ..http import endpoint, json_response, parse_body


@endpoint(['GET', 'POST'])
def guests_collection(request):
    if request.method == 'GET':
        return json_response(guest_service.list_guests(request.GET))
    return json_response(guest_service.create_guest(parse_body(request)), status=201)


@endpoint(['GET', 'PUT', 'DELETE'])
def guest_item(request, guest_id):
    guest_id = int(guest_id)
    if request.method == 'GET':
        return json_response(guest_service.get_guest(guest_id))
    if request.method == 'PUT':
        return json_response(guest_service.update_guest(guest_id, parse_body(request)))
    guest_service.delete_guest(guest_id)
    return json_response({'deleted': guest_id})


@endpoint(['GET'])
def guest_bookings(request, guest_id):
    return json_response(booking_service.list_bookings_of_guest(int(guest_id), request.GET))
