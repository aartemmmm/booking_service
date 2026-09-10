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

# Единственное подключение к PostgreSQL.
# Реальные SQL-запросы выполняются в слое main/repositories.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'booking_service'),
        'USER': os.getenv('POSTGRES_USER', 'booking'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'booking'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': int(os.getenv('POSTGRES_CONN_MAX_AGE', '60')),
    }
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
