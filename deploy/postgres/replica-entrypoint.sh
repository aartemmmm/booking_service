#!/bin/sh
#
# Точка входа контейнера Replica.
#
# При первом запуске каталог данных пуст: снимаем базовую копию с Primary
# командой pg_basebackup. Ключ --write-recovery-conf кладёт в каталог данных
# файл standby.signal и параметр primary_conninfo — благодаря им сервер стартует
# как hot standby и сам подключается к Primary за потоком WAL.
#
# При последующих запусках копия уже есть, и управление сразу передаётся
# штатному entrypoint образа.
set -eu

PGDATA="${PGDATA:-/var/lib/postgresql/data}"
PRIMARY_HOST="${PRIMARY_HOST:-postgres}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
REPLICATION_USER="${REPLICATION_USER:-replicator}"
REPLICATION_SLOT="${REPLICATION_SLOT:-replica_1}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "Каталог данных пуст — снимаю базовую копию с Primary ${PRIMARY_HOST}:${PRIMARY_PORT}..."
    until pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATION_USER" >/dev/null 2>&1; do
        sleep 1
    done

    # Слот мог остаться от прошлой реплики (том пересоздан): без этого --create-slot упадёт
    PGPASSWORD="$REPLICATION_PASSWORD" psql -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" \
        -U "$REPLICATION_USER" -d "${POSTGRES_DB:-postgres}" -qAt -c \
        "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots
          WHERE slot_name = '$REPLICATION_SLOT' AND NOT active" || true

    mkdir -p "$PGDATA"
    chown postgres:postgres "$PGDATA"
    chmod 700 "$PGDATA"

    PGPASSWORD="$REPLICATION_PASSWORD" su-exec postgres pg_basebackup \
        --host="$PRIMARY_HOST" --port="$PRIMARY_PORT" --username="$REPLICATION_USER" \
        --pgdata="$PGDATA" \
        --format=plain --wal-method=stream \
        --checkpoint=fast --progress \
        --create-slot --slot="$REPLICATION_SLOT" \
        --write-recovery-conf

    echo "Базовая копия готова, сервер стартует как hot standby."
fi

exec docker-entrypoint.sh "$@"
