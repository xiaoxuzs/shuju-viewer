-- viewer-migration: transactional

CREATE TABLE public.schema_migrations (
    version integer PRIMARY KEY,
    name varchar(200) NOT NULL UNIQUE,
    checksum varchar(64) NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    applied_by text NOT NULL,
    execution_ms bigint NOT NULL,
    application_version text NOT NULL,
    git_commit varchar(64),
    database_server_version_num integer NOT NULL,

    CONSTRAINT ck_schema_migrations_version
        CHECK (version > 0),

    CONSTRAINT ck_schema_migrations_checksum
        CHECK (checksum ~ '^[0-9a-f]{64}$'),

    CONSTRAINT ck_schema_migrations_applied_by
        CHECK (btrim(applied_by) <> ''),

    CONSTRAINT ck_schema_migrations_execution_ms
        CHECK (execution_ms >= 0),

    CONSTRAINT ck_schema_migrations_application_version
        CHECK (btrim(application_version) <> ''),

    CONSTRAINT ck_schema_migrations_git_commit
        CHECK (
            git_commit IS NULL
            OR git_commit ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
        ),

    CONSTRAINT ck_schema_migrations_server_version
        CHECK (database_server_version_num > 0)
);

CREATE FUNCTION public.schema_migrations_reject_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $viewer_schema_migrations$
BEGIN
    RAISE EXCEPTION 'public.schema_migrations is append-only: % is not allowed', TG_OP
        USING ERRCODE = '55000';
END;
$viewer_schema_migrations$;

CREATE TRIGGER schema_migrations_reject_update_delete
BEFORE UPDATE OR DELETE ON public.schema_migrations
FOR EACH STATEMENT
EXECUTE FUNCTION public.schema_migrations_reject_mutation();

CREATE TRIGGER schema_migrations_reject_truncate
BEFORE TRUNCATE ON public.schema_migrations
FOR EACH STATEMENT
EXECUTE FUNCTION public.schema_migrations_reject_mutation();
