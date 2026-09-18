"""
Настройки backend-сервиса бронирования отеля.

Все параметры подключения к PostgreSQL берутся из переменных окружения,
чтобы одно и то же приложение запускалось и локально, и в Docker Compose.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default='false'):
    return os.getenv(name, default).lower() in {'1', 'true', 'yes', 'on'}


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-local-development-key')

DEBUG = env_bool('DJANGO_DEBUG', 'true')

ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    'main',
]

MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'booking_service.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [],
        },
    },
]

WSGI_APPLICATION = 'booking_service.wsgi.application'
ASGI_APPLICATION = 'booking_service.asgi.application'

# Подключения к PostgreSQL. Реальные SQL-запросы выполняются в слое main/repositories.
#   'default'   — Primary: все записи (INSERT/UPDATE/DELETE) и чтение по умолчанию;
#   'replica-1' — Replica: список и подсчёт бронирований (main/repositories/booking_repository.py);
#   'replica-2' — вторая Replica: список гостей (main/repositories/guest_repository.py).
# Обеим репликам допустимо небольшое отставание данных (replication lag).
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'booking_service'),
        'USER': os.getenv('POSTGRES_USER', 'booking'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'booking'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': int(os.getenv('POSTGRES_CONN_MAX_AGE', '60')),
        # application_name видно в pg_stat_activity и в логах сервера
        'OPTIONS': {'application_name': 'booking-backend'},
    },
}

# Если хост реплики не задан переменной окружения, алиас указывает на Primary,
# и сервис работает без реплики. Соединение при этом всё равно открывается
# в режиме только чтения (default_transaction_read_only), поэтому запись
# через 'replica-1' / 'replica-2' невозможна ни при какой конфигурации.
DATABASES['replica-1'] = {
    **DATABASES['default'],
    'HOST': os.getenv('POSTGRES_REPLICA_1_HOST') or DATABASES['default']['HOST'],
    'PORT': os.getenv('POSTGRES_REPLICA_1_PORT') or DATABASES['default']['PORT'],
    'OPTIONS': {
        'application_name': 'booking-backend-replica-1',
        'options': '-c default_transaction_read_only=on',
    },
}

DATABASES['replica-2'] = {
    **DATABASES['default'],
    'HOST': os.getenv('POSTGRES_REPLICA_2_HOST') or DATABASES['default']['HOST'],
    'PORT': os.getenv('POSTGRES_REPLICA_2_PORT') or DATABASES['default']['PORT'],
    'OPTIONS': {
        'application_name': 'booking-backend-replica-2',
        'options': '-c default_transaction_read_only=on',
    },
}
# Шарды бронирований: независимые экземпляры PostgreSQL, между которыми
# распределяется таблица bookings. Порядок в списке важен — по нему router
# нумерует шарды (hash(id_guest) % N выбирает индекс в этом списке).
# По умолчанию шарды ищутся на хосте (порты 5440–5442); в Docker адреса
# передаются переменными SHARD_<i>_HOST / SHARD_<i>_PORT.
BOOKING_SHARDS = ['shard_0', 'shard_1', 'shard_2']

for _index, _alias in enumerate(BOOKING_SHARDS):
    DATABASES[_alias] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('SHARD_DB', 'booking_shard'),
        'USER': os.getenv('POSTGRES_USER', 'booking'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'booking'),
        'HOST': os.getenv(f'SHARD_{_index}_HOST', 'localhost'),
        'PORT': os.getenv(f'SHARD_{_index}_PORT', str(5440 + _index)),
        'CONN_MAX_AGE': int(os.getenv('POSTGRES_CONN_MAX_AGE', '60')),
        'OPTIONS': {'application_name': f'booking-backend-{_alias}'},
    }

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

# Значения по умолчанию для пагинации API
API_DEFAULT_PAGE_SIZE = int(os.getenv('API_DEFAULT_PAGE_SIZE', '20'))
API_MAX_PAGE_SIZE = int(os.getenv('API_MAX_PAGE_SIZE', '200'))

# Уведомления о состоянии партиций (manage.py check_partitions).
# По умолчанию письма складываются в файлы в каталоге alerts/ — это позволяет
# увидеть, что alert действительно отправлен, без настройки внешнего SMTP.
# Для реальной отправки достаточно задать DJANGO_EMAIL_BACKEND и параметры SMTP
# через переменные окружения.
EMAIL_BACKEND = os.getenv('DJANGO_EMAIL_BACKEND', 'django.core.mail.backends.filebased.EmailBackend')
EMAIL_FILE_PATH = os.getenv('DJANGO_EMAIL_FILE_PATH', str(BASE_DIR / 'alerts'))
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'false').lower() == 'true'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'partition-monitor@booking-service.local')
PARTITION_ALERT_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv('PARTITION_ALERT_RECIPIENTS', 'dba@booking-service.local').split(',')
    if addr.strip()
]
