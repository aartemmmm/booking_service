"""Отчёты на агрегирующих запросах."""

from ...services import report_service
from ..http import endpoint, json_response


@endpoint(['GET'])
def revenue_by_room_type(request):
    return json_response(report_service.revenue_by_room_type(request.GET))


@endpoint(['GET'])
def top_guests(request):
    return json_response(report_service.top_guests(request.GET))
