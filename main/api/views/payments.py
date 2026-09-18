"""Платежи по бронированиям."""

from ...services import payment_service
from ..http import endpoint, json_response, parse_body


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
