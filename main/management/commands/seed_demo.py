"""
Небольшой набор тестовых данных для проверки API.

Команда идемпотентна: повторный запуск не создаёт дублей.
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction

SEED_SQL = """
INSERT INTO roomtypes (id_type, name, description, price_per_night) VALUES
    (1, 'Стандарт', 'Одноместный номер с рабочим местом', 4200.00),
    (2, 'Бизнес', 'Двухместный номер с зоной отдыха', 6200.00),
    (3, 'Люкс', 'Просторный номер с панорамными окнами', 9800.00)
ON CONFLICT (id_type) DO NOTHING;

INSERT INTO rooms (id_room, room_number, id_type, floor, status) VALUES
    (1, '101', 1, 1, 'available'),
    (2, '102', 1, 1, 'occupied'),
    (3, '201', 2, 2, 'occupied'),
    (4, '202', 2, 2, 'cleaning'),
    (5, '301', 3, 3, 'maintenance')
ON CONFLICT (id_room) DO NOTHING;

INSERT INTO guests (id_guest, last_name, first_name, middle_name, phone, email, passport_number, created_at) VALUES
    (1, 'Иванов', 'Алексей', 'Петрович', '+79990000011', 'alexey.ivanov@example.com', '4005123456', NOW()),
    (2, 'Полякова', 'Елена', 'Сергеевна', '+79990000022', 'elena.polyakova@example.com', '4506987654', NOW()),
    (3, 'Смирнов', 'Максим', NULL, '+79990000033', 'max.smirnov@example.com', '4511223344', NOW()),
    (4, 'Громов', 'Ярослав', 'Игоревич', '+79990000044', 'yaroslav.gromov@example.com', '4509112233', NOW())
ON CONFLICT (id_guest) DO NOTHING;

INSERT INTO services (id_service, name, description, price) VALUES
    (1, 'Поздний выезд', 'Продление проживания до 16:00', 1500.00),
    (2, 'Трансфер в аэропорт', 'Индивидуальный трансфер', 3500.00),
    (3, 'Завтрак в номер', 'Комплексный завтрак на выбор', 900.00),
    (4, 'SPA-день', 'Доступ в SPA-зону и массаж 60 минут', 5200.00)
ON CONFLICT (id_service) DO NOTHING;

INSERT INTO employees (id_employee, last_name, first_name, middle_name, position, phone, hire_date) VALUES
    (1, 'Васильева', 'Марина', 'Олеговна', 'Администратор', '+79997770011', '2023-03-15'),
    (2, 'Журавлев', 'Дмитрий', 'Андреевич', 'Менеджер сервиса', '+79997770022', '2022-10-01'),
    (3, 'Ким', 'Светлана', 'Викторовна', 'Горничная', '+79997770033', '2024-01-20'),
    (4, 'Егоров', 'Семен', 'Павлович', 'Техник', '+79997770044', '2023-06-05')
ON CONFLICT (id_employee) DO NOTHING;

INSERT INTO employeeroles (id_role, name) VALUES
    (1, 'Администратор фронт-деск'),
    (2, 'Сервис-менеджер'),
    (3, 'Служба уборки'),
    (4, 'Инженер службы эксплуатации')
ON CONFLICT (id_role) DO NOTHING;

INSERT INTO employeeroleassignments (id_employee, id_role) VALUES
    (1, 1), (2, 2), (3, 3), (4, 4), (1, 2)
ON CONFLICT (id_employee, id_role) DO NOTHING;

INSERT INTO bookings (id_booking, id_guest, id_room, check_in, check_out, total_price, status, created_at, updated_at) VALUES
    (1, 1, 2, '2026-01-10', '2026-01-15', 21000.00, 'confirmed', NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'),
    (2, 2, 3, '2026-01-12', '2026-01-16', 24800.00, 'checked_in', NOW() - INTERVAL '15 days', NOW() - INTERVAL '15 days'),
    (3, 3, 1, '2026-01-05', '2026-01-07', 8400.00, 'checked_out', NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days'),
    (4, 4, 4, '2026-02-01', '2026-02-03', 12400.00, 'pending', NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days')
ON CONFLICT (id_booking) DO NOTHING;

INSERT INTO bookingservices (id_booking, id_service, quantity) VALUES
    (1, 1, 1), (1, 3, 2), (2, 2, 1), (2, 3, 4), (3, 3, 1), (4, 4, 2)
ON CONFLICT (id_booking, id_service) DO NOTHING;

INSERT INTO payments (id_payment, id_booking, payment_date, amount, method, status, created_at) VALUES
    (1, 1, '2026-01-09', 21000.00, 'card', 'success', NOW()),
    (2, 2, '2026-01-12', 12000.00, 'cash', 'partial', NOW()),
    (3, 3, '2026-01-05', 8400.00, 'card', 'success', NOW()),
    (4, 4, '2026-01-30', 12400.00, 'online', 'pending', NOW())
ON CONFLICT (id_payment) DO NOTHING;

INSERT INTO roomcleanings (id_cleaning, id_room, id_employee, cleaning_date, cleaning_start, cleaning_end, cleaning_status, cleaning_type, notes) VALUES
    (1, 1, 3, '2026-01-07', '2026-01-07 10:00+00', '2026-01-07 10:45+00', 'completed', 'checkout', 'Гость выехал'),
    (2, 4, 3, '2026-01-08', '2026-01-08 08:30+00', NULL, 'in_progress', 'deep', 'Требуется проверка техники'),
    (3, 5, 4, '2026-01-09', '2026-01-09 09:15+00', '2026-01-09 10:30+00', 'completed', 'maintenance', 'Замена смесителя')
ON CONFLICT (id_cleaning) DO NOTHING;
"""

# После вставки строк с явными id последовательности нужно сдвинуть,
# иначе INSERT из API упрётся в конфликт первичного ключа.
SEQUENCES = [
    ('roomtypes', 'id_type'),
    ('rooms', 'id_room'),
    ('guests', 'id_guest'),
    ('services', 'id_service'),
    ('employees', 'id_employee'),
    ('employeeroles', 'id_role'),
    ('bookings', 'id_booking'),
    ('payments', 'id_payment'),
    ('roomcleanings', 'id_cleaning'),
]


class Command(BaseCommand):
    help = 'Загрузить небольшой демонстрационный набор данных.'

    @transaction.atomic
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(SEED_SQL)
            for table, column in SEQUENCES:
                cursor.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', '{column}'),
                        COALESCE((SELECT MAX({column}) FROM {table}), 1)
                    )
                    """
                )
        self.stdout.write(self.style.SUCCESS('Демонстрационные данные загружены.'))
