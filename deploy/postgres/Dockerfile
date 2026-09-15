# PostgreSQL с расширением pg_cron — планировщиком задач внутри базы данных.
#
# В официальном образе postgres:16-alpine pg_cron нет, поэтому расширение
# собирается из исходников. Базовый образ сохранён прежним (Alpine, musl):
# при переходе на Debian-образ (glibc) изменились бы правила сортировки строк,
# и текстовые индексы в уже существующем томе с данными стали бы некорректными.

FROM postgres:16-alpine

ARG PG_CRON_VERSION=v1.6.4

RUN set -eux; \
    apk add --no-cache --virtual .build-deps git build-base; \
    git clone --depth 1 --branch "$PG_CRON_VERSION" \
        https://github.com/citusdata/pg_cron.git /tmp/pg_cron; \
    cd /tmp/pg_cron; \
    # with_llvm=no: не собирать JIT-биткод, для расширения-планировщика он не нужен
    make with_llvm=no; \
    make with_llvm=no install; \
    cd /; \
    rm -rf /tmp/pg_cron; \
    apk del .build-deps

# Точка входа для Replica: при пустом каталоге данных снимает копию с Primary
# (pg_basebackup), затем передаёт управление штатному entrypoint образа.
COPY replica-entrypoint.sh /usr/local/bin/replica-entrypoint.sh
RUN chmod +x /usr/local/bin/replica-entrypoint.sh
