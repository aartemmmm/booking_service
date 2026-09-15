-- =============================================================================
-- Автоматическое создание партиций и контроль их наличия через pg_cron.
--
-- Скрипт идемпотентен: его можно выполнять повторно, существующие объекты
-- заменяются, задачи расписания обновляются по имени.
--
-- На пустом томе PostgreSQL выполняет его сам (каталог docker-entrypoint-initdb.d).
-- На уже существующей базе применяется вручную:
--   docker exec -i booking_postgres psql -U booking -d booking_service \
--       < deploy/postgres/initdb/10-partitions-pg-cron.sql
--
-- Все даты считаются в UTC, как и расписание pg_cron (cron.timezone = UTC).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE SCHEMA IF NOT EXISTS lab3;


-- -----------------------------------------------------------------------------
-- Таблицы
-- -----------------------------------------------------------------------------

-- Журнал запусков. pg_cron сам пишет в cron.job_run_details только
-- «succeeded/failed», поэтому подробности работы job сохраняются здесь.
CREATE TABLE IF NOT EXISTS lab3.partition_job_log (
    id        BIGSERIAL PRIMARY KEY,
    job       TEXT        NOT NULL,              -- create | check
    target    TEXT        NOT NULL,              -- lab3.events
    status    TEXT        NOT NULL,              -- OK | CREATED | CRITICAL
    existing  INT,
    required  INT,
    missing   TEXT[]      NOT NULL DEFAULT '{}',
    created   TEXT[]      NOT NULL DEFAULT '{}',
    message   TEXT,
    run_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Последнее известное состояние каждой таблицы — нужно, чтобы не слать
-- одинаковый alert при каждой проверке.
CREATE TABLE IF NOT EXISTS lab3.partition_alert_state (
    target     TEXT PRIMARY KEY,
    status     TEXT        NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE lab3.partition_alert_state
    ADD COLUMN IF NOT EXISTS checked_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Очередь уведомлений. База не умеет отправлять письма, поэтому проверка
-- кладёт уведомление сюда и подаёт сигнал NOTIFY, а отправляет его
-- слушатель на стороне приложения (manage.py partition_alert_listener).
CREATE TABLE IF NOT EXISTS lab3.partition_alerts (
    id         BIGSERIAL PRIMARY KEY,
    target     TEXT        NOT NULL,
    kind       TEXT        NOT NULL,             -- CRITICAL | RECOVERY
    subject    TEXT        NOT NULL,
    body       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS partition_alerts_pending_idx
    ON lab3.partition_alerts (id) WHERE sent_at IS NULL;


-- -----------------------------------------------------------------------------
-- Какие партиции должны существовать: текущий период + p_horizon вперёд.
-- Горизонт 3 дня = 4 партиции: сегодня и три следующих дня.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lab3.required_partitions(
    p_table       TEXT,
    p_granularity TEXT,
    p_horizon     INT
)
RETURNS TABLE (partition_name TEXT, range_start DATE, range_end DATE)
LANGUAGE plpgsql STABLE
AS $$
DECLARE
    v_today DATE := (now() AT TIME ZONE 'UTC')::date;
    v_start DATE;
BEGIN
    IF p_granularity NOT IN ('day', 'month') THEN
        RAISE EXCEPTION 'Неизвестная гранулярность: %', p_granularity;
    END IF;
    IF p_horizon < 0 THEN
        RAISE EXCEPTION 'Горизонт не может быть отрицательным: %', p_horizon;
    END IF;

    FOR i IN 0..p_horizon LOOP
        IF p_granularity = 'day' THEN
            v_start        := v_today + i;
            partition_name := format('%s_%s', p_table, to_char(v_start, 'YYYY_MM_DD'));
            range_end      := v_start + 1;
        ELSE
            v_start        := (date_trunc('month', v_today) + make_interval(months => i))::date;
            partition_name := format('%s_%s', p_table, to_char(v_start, 'YYYY_MM'));
            range_end      := (v_start + INTERVAL '1 month')::date;
        END IF;
        range_start := v_start;
        RETURN NEXT;
    END LOOP;
END;
$$;


-- Проверка, что таблица существует и действительно партиционирована.
CREATE OR REPLACE FUNCTION lab3.assert_partitioned(p_schema TEXT, p_table TEXT)
RETURNS VOID
LANGUAGE plpgsql STABLE
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_partitioned_table pt
        JOIN pg_class c     ON c.oid = pt.partrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = p_schema AND c.relname = p_table
    ) THEN
        RAISE EXCEPTION 'Таблица %.% не найдена или не партиционирована', p_schema, p_table;
    END IF;
END;
$$;


-- Имена партиций, реально существующих у таблицы (из системного каталога).
CREATE OR REPLACE FUNCTION lab3.existing_partitions(p_schema TEXT, p_table TEXT)
RETURNS SETOF TEXT
LANGUAGE sql STABLE
AS $$
    SELECT child.relname::text
    FROM pg_inherits i
    JOIN pg_class child  ON child.oid  = i.inhrelid
    JOIN pg_class parent ON parent.oid = i.inhparent
    JOIN pg_namespace n  ON n.oid      = parent.relnamespace
    WHERE n.nspname = p_schema AND parent.relname = p_table
$$;


-- -----------------------------------------------------------------------------
-- CreatePartitionsJob: создать недостающие партиции.
--
-- Безопасна при повторном запуске: уже существующие партиции отсеиваются
-- сверкой с каталогом, а CREATE TABLE IF NOT EXISTS страхует от гонки
-- с параллельным запуском.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lab3.create_missing_partitions(
    p_schema      TEXT,
    p_table       TEXT,
    p_granularity TEXT    DEFAULT 'day',
    p_horizon     INT     DEFAULT 3,
    p_dry_run     BOOLEAN DEFAULT false,
    OUT status    TEXT,
    OUT report    TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_existing INT;
    v_required INT;
    v_missing  TEXT[] := '{}';
    v_created  TEXT[] := '{}';
    v_lines    TEXT[];
    r          RECORD;
BEGIN
    PERFORM lab3.assert_partitioned(p_schema, p_table);

    SELECT count(*) INTO v_existing FROM lab3.existing_partitions(p_schema, p_table);
    SELECT count(*) INTO v_required FROM lab3.required_partitions(p_table, p_granularity, p_horizon);

    v_lines := ARRAY[
        to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || ' UTC',
        '',
        'Partition job started.',
        ''
    ];

    FOR r IN
        SELECT rp.*
        FROM lab3.required_partitions(p_table, p_granularity, p_horizon) rp
        WHERE rp.partition_name NOT IN (SELECT lab3.existing_partitions(p_schema, p_table))
        ORDER BY rp.range_start
    LOOP
        v_missing := v_missing || r.partition_name;
        IF NOT p_dry_run THEN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
                p_schema, r.partition_name, p_schema, p_table, r.range_start, r.range_end
            );
            v_created := v_created || format('%s [%s .. %s)', r.partition_name, r.range_start, r.range_end);
        END IF;
    END LOOP;

    v_lines := v_lines || ARRAY[
        'Existing partitions: ' || v_existing,
        'Required partitions: ' || v_required,
        'Missing partitions: '  || cardinality(v_missing),
        ''
    ];

    IF cardinality(v_missing) = 0 THEN
        status  := 'OK';
        v_lines := v_lines || ARRAY['Nothing to create, all required partitions already exist.'];
    ELSE
        v_lines := v_lines || 'Creating:'::text || v_missing || ''::text;
        IF p_dry_run THEN
            status  := 'DRY_RUN';
            v_lines := v_lines || ARRAY['Dry run: партиции не создавались.'];
        ELSE
            status := 'CREATED';
            SELECT v_lines || array_agg('Partition created successfully: ' || c)
              INTO v_lines
              FROM unnest(v_created) AS c;
        END IF;
    END IF;

    v_lines := v_lines || ARRAY['', 'Partition job finished.'];
    report  := array_to_string(v_lines, E'\n');

    IF NOT p_dry_run THEN
        INSERT INTO lab3.partition_job_log (job, target, status, existing, required, missing, created)
        VALUES ('create', p_schema || '.' || p_table, status, v_existing, v_required, v_missing, v_created);
    END IF;
END;
$$;


-- -----------------------------------------------------------------------------
-- PartitionHealthCheck: все ли требуемые партиции существуют.
--
-- При смене состояния кладёт уведомление в lab3.partition_alerts и подаёт
-- сигнал NOTIFY partition_alert. Пока проблема держится, повторные
-- уведомления не создаются; при восстановлении создаётся recovery.
--   08:00 CRITICAL -> alert
--   08:05 CRITICAL -> подавлен
--   08:15 OK       -> recovery
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lab3.check_partitions(
    p_schema      TEXT,
    p_table       TEXT,
    p_granularity TEXT DEFAULT 'day',
    p_horizon     INT  DEFAULT 3,
    OUT status    TEXT,
    OUT report    TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_target     TEXT := p_schema || '.' || p_table;
    v_checked_at TEXT := to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS');
    v_unit       TEXT := CASE p_granularity WHEN 'day' THEN 'days' ELSE 'months' END;
    v_missing    TEXT[];
    v_marks      TEXT[];
    v_previous   TEXT;
    v_alert_id   BIGINT;
    v_action     TEXT;
BEGIN
    PERFORM lab3.assert_partitioned(p_schema, p_table);

    SELECT
        coalesce(array_agg(rp.partition_name ORDER BY rp.range_start)
                 FILTER (WHERE e.name IS NULL), '{}'),
        array_agg(CASE WHEN e.name IS NULL THEN '  ✗ ' ELSE '  ✓ ' END || rp.partition_name
                  ORDER BY rp.range_start)
    INTO v_missing, v_marks
    FROM lab3.required_partitions(p_table, p_granularity, p_horizon) rp
    LEFT JOIN lab3.existing_partitions(p_schema, p_table) AS e(name)
           ON e.name = rp.partition_name;

    status := CASE WHEN cardinality(v_missing) > 0 THEN 'CRITICAL' ELSE 'OK' END;

    SELECT s.status INTO v_previous
    FROM lab3.partition_alert_state s
    WHERE s.target = v_target
    FOR UPDATE;

    IF status = 'CRITICAL' AND v_previous IS DISTINCT FROM 'CRITICAL' THEN
        INSERT INTO lab3.partition_alerts (target, kind, subject, body)
        VALUES (
            v_target, 'CRITICAL',
            format('[CRITICAL] Partition alert: %s', p_table),
            array_to_string(
                ARRAY['🚨 Partition alert', '', 'Table: ' || p_table, '', 'Missing partitions:']
                || v_missing
                || ARRAY['', format('Expected horizon: %s %s', p_horizon, v_unit), '',
                         'Checked at:', v_checked_at || ' UTC'],
                E'\n')
        )
        RETURNING id INTO v_alert_id;
        PERFORM pg_notify('partition_alert', v_alert_id::text);
        v_action := format('Уведомление поставлено в очередь: lab3.partition_alerts id=%s', v_alert_id);

    ELSIF status = 'CRITICAL' THEN
        v_action := 'Состояние не изменилось с прошлой проверки — alert подавлен.';

    ELSIF v_previous = 'CRITICAL' THEN
        INSERT INTO lab3.partition_alerts (target, kind, subject, body)
        VALUES (
            v_target, 'RECOVERY',
            format('[OK] Partition check recovered: %s', p_table),
            array_to_string(
                ARRAY['🟢 Partition check OK', '', 'Table: ' || p_table, '',
                      'All required partitions exist.', '', 'Checked at:', v_checked_at || ' UTC'],
                E'\n')
        )
        RETURNING id INTO v_alert_id;
        PERFORM pg_notify('partition_alert', v_alert_id::text);
        v_action := format('Recovery поставлен в очередь: lab3.partition_alerts id=%s', v_alert_id);

    ELSE
        v_action := 'Состояние не изменилось с прошлой проверки — уведомлений нет.';
    END IF;

    INSERT INTO lab3.partition_alert_state AS s (target, status, changed_at, checked_at)
    VALUES (v_target, status, now(), now())
    ON CONFLICT (target) DO UPDATE
        SET status     = EXCLUDED.status,
            changed_at = CASE WHEN s.status <> EXCLUDED.status THEN now() ELSE s.changed_at END,
            checked_at = now();

    INSERT INTO lab3.partition_job_log (job, target, status, missing, message)
    VALUES ('check', v_target, status, v_missing, v_action);

    report := array_to_string(
        ARRAY['PartitionHealthCheck: ' || v_target, 'Checked at: ' || v_checked_at || ' UTC', '']
        || v_marks
        || ARRAY['',
                 CASE WHEN status = 'CRITICAL'
                      THEN format('Результат проверки: CRITICAL (отсутствует партиций: %s)', cardinality(v_missing))
                      ELSE 'Результат проверки: OK' END,
                 v_action],
        E'\n');
END;
$$;


-- -----------------------------------------------------------------------------
-- Расписание. cron.schedule с тем же именем обновляет задачу, а не дублирует.
-- Проверка идёт через 5 минут после создания: если бы обе задачи стартовали
-- в одну минуту, проверка могла бы успеть раньше и дать ложный CRITICAL.
-- -----------------------------------------------------------------------------

-- Учебная таблица событий: партиции по дням, горизонт 3 дня
SELECT cron.schedule(
    'lab3-events-create-partitions',
    '0 1 * * *',
    $$SELECT lab3.create_missing_partitions('lab3', 'events', 'day', 3)$$
);
SELECT cron.schedule(
    'lab3-events-check-partitions',
    '5 1 * * *',
    $$SELECT lab3.check_partitions('lab3', 'events', 'day', 3)$$
);

-- Партиционированная копия bookings: партиции по месяцам, горизонт 3 месяца
SELECT cron.schedule(
    'lab3-bookings-create-partitions',
    '0 1 * * *',
    $$SELECT lab3.create_missing_partitions('lab3', 'bookings_partitioned', 'month', 3)$$
);
SELECT cron.schedule(
    'lab3-bookings-check-partitions',
    '5 1 * * *',
    $$SELECT lab3.check_partitions('lab3', 'bookings_partitioned', 'month', 3)$$
);
