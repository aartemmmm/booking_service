"""Служебные обработчики: проверка состояния и документация API."""

from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render

from ...services import health_service
from ..http import endpoint, json_response


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
