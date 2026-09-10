"""Корневой URL-конфиг сервиса бронирования."""

from django.urls import include, path

urlpatterns = [
    path('', include('main.urls')),
]

handler404 = 'main.api.views.not_found'
handler500 = 'main.api.views.server_error'
