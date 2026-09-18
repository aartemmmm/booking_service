"""Маршруты API. Обработчики — в пакете main/api/views/, по файлу на ресурс."""

from django.urls import re_path

from .api import views

urlpatterns = [
    re_path(r'^health/?$', views.health, name='health'),
    re_path(r'^docs/?$', views.docs, name='docs'),
    re_path(r'^openapi\.yaml$', views.openapi_spec, name='openapi'),

    # bookings — основная растущая сущность
    re_path(r'^api/bookings/?$', views.bookings_collection, name='bookings'),
    re_path(r'^api/bookings/(?P<booking_id>\d+)/?$', views.booking_item, name='booking'),
    re_path(
        r'^api/bookings/(?P<booking_id>\d+)/services/?$',
        views.booking_services,
        name='booking-services',
    ),
    re_path(
        r'^api/bookings/(?P<booking_id>\d+)/services/(?P<service_id>\d+)/?$',
        views.booking_service_item,
        name='booking-service',
    ),
    re_path(
        r'^api/bookings/(?P<booking_id>\d+)/payments/?$',
        views.booking_payments,
        name='booking-payments',
    ),

    # guests
    re_path(r'^api/guests/?$', views.guests_collection, name='guests'),
    re_path(r'^api/guests/(?P<guest_id>\d+)/?$', views.guest_item, name='guest'),
    re_path(
        r'^api/guests/(?P<guest_id>\d+)/bookings/?$', views.guest_bookings, name='guest-bookings'
    ),

    # rooms
    re_path(r'^api/rooms/?$', views.rooms_collection, name='rooms'),
    re_path(r'^api/rooms/(?P<room_id>\d+)/?$', views.room_item, name='room'),
    re_path(r'^api/rooms/(?P<room_id>\d+)/bookings/?$', views.room_bookings, name='room-bookings'),

    # room types
    re_path(r'^api/room-types/?$', views.room_types_collection, name='room-types'),
    re_path(r'^api/room-types/(?P<type_id>\d+)/?$', views.room_type_item, name='room-type'),

    # services
    re_path(r'^api/services/?$', views.services_collection, name='services'),
    re_path(r'^api/services/(?P<service_id>\d+)/?$', views.service_item, name='service'),

    # payments
    re_path(r'^api/payments/?$', views.payments_collection, name='payments'),
    re_path(r'^api/payments/(?P<payment_id>\d+)/?$', views.payment_item, name='payment'),

    # отчёты на агрегирующих запросах
    re_path(
        r'^api/reports/revenue-by-room-type/?$',
        views.revenue_by_room_type,
        name='report-revenue-by-room-type',
    ),
    re_path(r'^api/reports/top-guests/?$', views.top_guests, name='report-top-guests'),
]
