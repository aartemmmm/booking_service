#!/bin/sh
set -e

echo "Ожидание PostgreSQL на ${POSTGRES_HOST}:${POSTGRES_PORT}..."
until pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" >/dev/null 2>&1; do
    sleep 1
done

echo "Применение миграций..."
python manage.py migrate --noinput

if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
    echo "Загрузка демонстрационных данных..."
    python manage.py seed_demo
fi

echo "Запуск backend на 0.0.0.0:8000"
exec python manage.py runserver 0.0.0.0:8000
