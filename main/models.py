"""
Модели описывают схему БД и нужны системе миграций Django.

Чтение и запись данных выполняются не через ORM, а через слой репозиториев
(main/repositories) обычными SQL-запросами.
"""

from django.db import models

BOOKING_STATUSES = ['pending', 'confirmed', 'checked_in', 'checked_out', 'cancelled']
PAYMENT_STATUSES = ['pending', 'success', 'partial', 'failed', 'refunded']
PAYMENT_METHODS = ['card', 'cash', 'transfer', 'online']
ROOM_STATUSES = ['available', 'occupied', 'cleaning', 'maintenance']


class RoomType(models.Model):
    id_type = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'roomtypes'


class Room(models.Model):
    id_room = models.AutoField(primary_key=True)
    room_number = models.CharField(max_length=20, unique=True)
    id_type = models.ForeignKey(RoomType, models.PROTECT, db_column='id_type', related_name='rooms')
    floor = models.IntegerField(blank=True, null=True)
    status = models.CharField(max_length=20, default='available')

    class Meta:
        db_table = 'rooms'


class Guest(models.Model):
    id_guest = models.AutoField(primary_key=True)
    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=32, unique=True, blank=True, null=True)
    email = models.CharField(max_length=255, unique=True, blank=True, null=True)
    passport_number = models.CharField(max_length=32, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'guests'


class Service(models.Model):
    id_service = models.AutoField(primary_key=True)
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'services'


class Booking(models.Model):
    """Основная растущая сущность сервиса."""

    id_booking = models.BigAutoField(primary_key=True)
    id_guest = models.ForeignKey(Guest, models.CASCADE, db_column='id_guest', related_name='bookings')
    id_room = models.ForeignKey(Room, models.PROTECT, db_column='id_room', related_name='bookings')
    check_in = models.DateField()
    check_out = models.DateField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bookings'
        # Индексы подобраны под реальные запросы API (см. docs/lab-01-indexes.md, задания 22-29).
        indexes = [
            # Лента бронирований без фильтра: ORDER BY created_at DESC LIMIT N.
            models.Index(fields=['-created_at'], name='idx_bookings_created_at'),
            # Лента с фильтром по статусу: WHERE status = ? ORDER BY created_at DESC LIMIT N.
            models.Index(fields=['status', '-created_at'], name='idx_bookings_status_created'),
            # Отчёты и выборки заездов: WHERE status = ? AND check_in BETWEEN ? AND ?.
            models.Index(fields=['status', 'check_in'], name='idx_bookings_status_check_in'),
        ]


class BookingService(models.Model):
    """Связь many-to-many между бронированиями и услугами."""

    pk = models.CompositePrimaryKey('id_booking', 'id_service')
    id_booking = models.ForeignKey(Booking, models.CASCADE, db_column='id_booking', related_name='booking_services')
    id_service = models.ForeignKey(Service, models.CASCADE, db_column='id_service', related_name='booking_services')
    quantity = models.IntegerField(default=1)

    class Meta:
        db_table = 'bookingservices'


class Payment(models.Model):
    id_payment = models.BigAutoField(primary_key=True)
    id_booking = models.ForeignKey(Booking, models.CASCADE, db_column='id_booking', related_name='payments')
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'


class Employee(models.Model):
    id_employee = models.AutoField(primary_key=True)
    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    position = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, unique=True, blank=True, null=True)
    hire_date = models.DateField()

    class Meta:
        db_table = 'employees'


class EmployeeRole(models.Model):
    id_role = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'employeeroles'


class EmployeeRoleAssignment(models.Model):
    """Связь many-to-many между сотрудниками и ролями."""

    pk = models.CompositePrimaryKey('id_employee', 'id_role')
    id_employee = models.ForeignKey(Employee, models.CASCADE, db_column='id_employee', related_name='role_assignments')
    id_role = models.ForeignKey(EmployeeRole, models.CASCADE, db_column='id_role', related_name='role_assignments')

    class Meta:
        db_table = 'employeeroleassignments'


class RoomCleaning(models.Model):
    id_cleaning = models.BigAutoField(primary_key=True)
    id_room = models.ForeignKey(Room, models.CASCADE, db_column='id_room', related_name='cleanings')
    id_employee = models.ForeignKey(Employee, models.PROTECT, db_column='id_employee', related_name='cleanings')
    cleaning_date = models.DateField()
    cleaning_start = models.DateTimeField()
    cleaning_end = models.DateTimeField(blank=True, null=True)
    cleaning_status = models.CharField(max_length=20, default='scheduled')
    cleaning_type = models.CharField(max_length=20, default='routine')
    notes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'roomcleanings'
