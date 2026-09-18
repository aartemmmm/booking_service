"""Номера и типы номеров."""

from ...services import booking_service, room_service
from ..http import endpoint, json_response, parse_body


# --------------------------------------------------------------------- rooms


@endpoint(['GET', 'POST'])
def rooms_collection(request):
    if request.method == 'GET':
        return json_response(room_service.list_rooms(request.GET))
    return json_response(room_service.create_room(parse_body(request)), status=201)


@endpoint(['GET', 'PUT', 'DELETE'])
def room_item(request, room_id):
    room_id = int(room_id)
    if request.method == 'GET':
        return json_response(room_service.get_room(room_id))
    if request.method == 'PUT':
        return json_response(room_service.update_room(room_id, parse_body(request)))
    room_service.delete_room(room_id)
    return json_response({'deleted': room_id})


@endpoint(['GET'])
def room_bookings(request, room_id):
    return json_response(booking_service.list_bookings_of_room(int(room_id), request.GET))


# ---------------------------------------------------------------- room types


@endpoint(['GET', 'POST'])
def room_types_collection(request):
    if request.method == 'GET':
        return json_response(room_service.list_room_types(request.GET))
    return json_response(room_service.create_room_type(parse_body(request)), status=201)


@endpoint(['GET', 'PUT', 'DELETE'])
def room_type_item(request, type_id):
    type_id = int(type_id)
    if request.method == 'GET':
        return json_response(room_service.get_room_type(type_id))
    if request.method == 'PUT':
        return json_response(room_service.update_room_type(type_id, parse_body(request)))
    room_service.delete_room_type(type_id)
    return json_response({'deleted': type_id})
