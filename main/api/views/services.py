"""Справочник дополнительных услуг."""

from ...services import catalog_service
from ..http import endpoint, json_response, parse_body


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
