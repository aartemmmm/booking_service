"""
HTTP-слой (контроллеры).

Обработчики не обращаются к базе напрямую: они разбирают запрос,
вызывают сервисный слой и сериализуют результат в JSON.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render

from ..services import (
    booking_service,
    catalog_service,
    guest_service,
    health_service,
    payment_service,
    report_service,
    room_service,
)
from .http import endpoint, error_response, json_response, parse_body


# ------------------------------------------------------------------ служебные


@endpoint(['GET'])
def health(request):
    """Проверка приложения и подключения к PostgreSQL."""
    payload, ok = health_service.check()
    return json_response(payload, status=200 if ok else 503)


@endpoint(['GET'])
def docs(request):
    """Swagger UI поверх спецификации OpenAPI."""
    return render(request, 'main/swagger.html')


@endpoint(['GET'])
def openapi_spec(request):
    """Спецификация OpenAPI 3.0 в формате YAML."""
    spec = Path(settings.BASE_DIR) / 'main' / 'openapi' / 'openapi.yaml'
    return HttpResponse(spec.read_text(encoding='utf-8'), content_type='application/yaml')


# ------------------------------------------------------------------ bookings


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


# -------------------------------------------------------------------- guests


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


# ------------------------------------------------------------------ services


@endpoint(['GET', 'POST'])
def services_collection(request):
    if request.method == 'GET':
        return json_response(catalog_service.list_services(request.GET))
    return json_response(catalog_service.create_service(parse_body(request)), status=201)


@endpoint(['GET', 'PUT', 'DELETE'])
def service_item(request, service_id):
    service_id = int(service_id)
    if request.method == 'GET':
        return json_response(catalog_service.get_service(service_id))
    if request.method == 'PUT':
        return json_response(catalog_service.update_service(service_id, parse_body(request)))
    catalog_service.delete_service(service_id)
    return json_response({'deleted': service_id})


# ------------------------------------------------------------------ payments


@endpoint(['GET', 'POST'])
def payments_collection(request):
    if request.method == 'GET':
        return json_response(payment_service.list_payments(request.GET))
    return json_response(payment_service.create_payment(parse_body(request)), status=201)


@endpoint(['GET', 'PUT', 'DELETE'])
def payment_item(request, payment_id):
    payment_id = int(payment_id)
    if request.method == 'GET':
        return json_response(payment_service.get_payment(payment_id))
    if request.method == 'PUT':
        return json_response(payment_service.update_payment(payment_id, parse_body(request)))
    payment_service.delete_payment(payment_id)
    return json_response({'deleted': payment_id})


# ------------------------------------------------------------------- reports


@endpoint(['GET'])
def revenue_by_room_type(request):
    return json_response(report_service.revenue_by_room_type(request.GET))


@endpoint(['GET'])
def top_guests(request):
    return json_response(report_service.top_guests(request.GET))


def not_found(request, exception=None):
    return error_response('Ресурс не найден.', 404)


def server_error(request):
    return error_response('Внутренняя ошибка сервиса.', 500)
