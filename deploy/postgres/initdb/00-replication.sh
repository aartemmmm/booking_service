#!/bin/bash
#
# Роль для streaming replication.
#
# Образ postgres выполняет этот файл при первой инициализации базы,
# то есть только на пустом томе. На уже существующей базе роль создаётся
# вручную тем же SQL — см. docs/lab-04-read-scaling.md, часть 2.
#
# Файлу нужны и строка #!, и бит исполнения (chmod +x). Entrypoint образа
# запускает .sh-файл, если считает его исполняемым, иначе подключает через ".".
# В каталоге, смонтированном с macOS, проверка -x может вернуть «да» и для
# файла без бита исполнения — тогда запуск падает с Permission denied, и
# инициализация базы останавливается. С битом исполнения работают оба пути.
#
# Атрибут REPLICATION разрешает роли открывать replication-подключения
# и получать WAL, но не даёт прав на данные.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${REPLICATION_USER:-replicator}') THEN
            CREATE ROLE "${REPLICATION_USER:-replicator}"
                WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD:-replicator}';
        END IF;
    END
    \$\$;
EOSQL
