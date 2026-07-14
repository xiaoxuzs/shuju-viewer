#!/usr/bin/env bash

set -Eeuo pipefail
umask 077
export LC_ALL=C
export LANG=C

readonly SCRIPT_VERSION="1"
readonly EXPECTED_PG_MAJOR="16"
readonly TEMP_BASE="/var/tmp"
readonly LOCK_FILE="/run/lock/viewer-native-pg16-test.lock"
readonly PRODUCTION_PG_SERVICE="postgresql@16-main.service"
readonly PRODUCTION_HOST="127.0.0.1"
readonly PRODUCTION_PORT="5432"
readonly PRODUCTION_IDENTITY="127.0.0.1:5432/Universal_Viewer"
readonly MIN_TEMP_FREE_BYTES=$((1024 * 1024 * 1024))
readonly MAX_PORT_ATTEMPTS=10

RUN_NON_POSTGRES=0
RUN_ID=""
RUN_ROOT=""
PGDATA=""
SOCKET_DIR=""
LOG_DIR=""
MARKER_FILE=""
TEST_ROLE=""
TEST_DATABASE=""
TEST_PORT=""
PYTEST_PID=""
CLEANUP_STARTED=0
CLEANUP_FAILED=0
DELETE_ALLOWED=1

PG_CONFIG=""
PG_BINDIR=""
PG_INITDB=""
PG_POSTGRES=""
PG_CTL=""
PG_ISREADY=""
PG_CREATEUSER=""
PG_CREATEDB=""
PG_PSQL=""
PYTHON=""
BACK_ROOT=""

PRODUCTION_DATA_ROOT=""
BASELINE_DATA_SUMMARY=""
BASELINE_PRODUCTION_PG_PID=""
BASELINE_UVICORN_PIDS=""
BASELINE_NGINX_PIDS=""

log() {
    printf '[viewer-pg16-test] %s\n' "$*"
}

error() {
    printf '[viewer-pg16-test] ERROR: %s\n' "$*" >&2
}

die() {
    error "$*"
    exit 1
}

usage() {
    printf '%s\n' \
        'Usage: run_native_postgres_tests.sh [--postgres-only|--with-non-postgres]' \
        '' \
        '  --postgres-only       Run only the isolated PostgreSQL tests (default).' \
        '  --with-non-postgres   Run the non-PostgreSQL regression after PostgreSQL tests pass.'
}

parse_arguments() {
    local mode_seen=0
    while (($#)); do
        case "$1" in
            --postgres-only)
                ((mode_seen == 0)) || die "Only one test mode may be selected"
                RUN_NON_POSTGRES=0
                mode_seen=1
                ;;
            --with-non-postgres)
                ((mode_seen == 0)) || die "Only one test mode may be selected"
                RUN_NON_POSTGRES=1
                mode_seen=1
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                die "Unknown argument: $1"
                ;;
        esac
        shift
    done
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command is unavailable: $1"
}

pg_run() {
    runuser -u postgres -- "$@"
}

is_postgres_16_version() {
    case "$1" in
        *"PostgreSQL 16."*|*"PostgreSQL) 16."*) return 0 ;;
        *) return 1 ;;
    esac
}

validate_run_id() {
    [[ "$1" =~ ^[0-9a-f]{32}$ ]]
}

validate_role_name() {
    [[ "$1" =~ ^viewer_test_runner_[0-9a-f]{16}$ ]]
}

validate_database_name() {
    [[ "$1" =~ ^viewer_test_imports_[0-9a-f]{16}$ ]]
}

validate_port() {
    local port="$1"
    [[ "$port" =~ ^[0-9]{5}$ ]] || return 1
    ((port >= 20000 && port <= 55000)) || return 1
    ((port != 5432 && port != 50001 && port != 50002))
}

validate_runtime_paths() {
    validate_run_id "$RUN_ID" || return 1
    [[ "$RUN_ROOT" == "$TEMP_BASE/viewer-pg16-test-$RUN_ID" ]] || return 1
    [[ "$PGDATA" == "$RUN_ROOT/data" ]] || return 1
    [[ "$SOCKET_DIR" == "$RUN_ROOT/socket" ]] || return 1
    [[ "$LOG_DIR" == "$RUN_ROOT/logs" ]] || return 1
    [[ "$MARKER_FILE" == "$RUN_ROOT/.viewer-pg16-test-owner" ]]
}

generate_hex() {
    local byte_count="$1"
    "$PYTHON" -B -c 'import secrets, sys; print(secrets.token_hex(int(sys.argv[1])))' "$byte_count"
}

capture_process_ids() {
    local mode="$1"
    local output=""
    case "$mode" in
        uvicorn)
            output="$(pgrep -f '[u]vicorn' 2>/dev/null | LC_ALL=C sort -n | paste -sd, - || true)"
            ;;
        nginx)
            output="$(pgrep -x nginx 2>/dev/null | LC_ALL=C sort -n | paste -sd, - || true)"
            ;;
        *)
            return 1
            ;;
    esac
    printf '%s' "$output"
}

production_postgres_pid() {
    local pid
    pid="$(systemctl show --property=MainPID --value "$PRODUCTION_PG_SERVICE")" || return 1
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    printf '%s' "$pid"
}

production_postgres_ready() {
    pg_run "$PG_ISREADY" \
        --host "$PRODUCTION_HOST" \
        --port "$PRODUCTION_PORT" \
        --timeout 5 >/dev/null
}

summarize_data_root() {
    local root="$1"
    local summary
    if ! summary="$(
        find -P "$root" -printf '%y\t%s\t%T@\n' |
            LC_ALL=C awk -F '\t' '
                BEGIN { files = 0; bytes = 0; latest = 0 }
                $1 == "f" { files += 1; bytes += $2 }
                $3 > latest { latest = $3 }
                END { printf "%d|%.0f|%.9f", files, bytes, latest }
            '
    )"; then
        return 1
    fi
    [[ "$summary" =~ ^[0-9]+\|[0-9]+\|[0-9]+([.][0-9]+)?$ ]] || return 1
    printf '%s' "$summary"
}

validate_production_data_root() {
    local supplied="${VIEWER_PRODUCTION_DATA_ROOT:-}"
    local resolved

    [[ -n "$supplied" ]] || die "VIEWER_PRODUCTION_DATA_ROOT must be explicitly provided"
    [[ "$supplied" == /* ]] || die "VIEWER_PRODUCTION_DATA_ROOT must be an absolute path"
    [[ -d "$supplied" ]] || die "VIEWER_PRODUCTION_DATA_ROOT does not exist or is not a directory"
    [[ ! -L "$supplied" ]] || die "VIEWER_PRODUCTION_DATA_ROOT must not be a symbolic link"
    resolved="$(realpath -e -- "$supplied")" || die "Unable to resolve VIEWER_PRODUCTION_DATA_ROOT"
    [[ -d "$resolved" ]] || die "Resolved VIEWER_PRODUCTION_DATA_ROOT is not a directory"
    [[ "$resolved" != "/" ]] || die "Production DATA_ROOT must not contain the temporary cluster root"
    [[ "$TEMP_BASE" != "$resolved" && "$TEMP_BASE" != "$resolved"/* ]] || die "Production DATA_ROOT must not contain the temporary cluster root"
    [[ "$resolved" != "$TEMP_BASE"/viewer-pg16-test-* ]] || die "Production DATA_ROOT overlaps a test run path"
    PRODUCTION_DATA_ROOT="$resolved"
}

check_free_space() {
    local available
    available="$(df -P -B1 "$TEMP_BASE" | awk 'NR == 2 { print $4 }')" || die "Unable to inspect $TEMP_BASE capacity"
    [[ "$available" =~ ^[0-9]+$ ]] || die "Invalid free-space result for $TEMP_BASE"
    ((available >= MIN_TEMP_FREE_BYTES)) || die "$TEMP_BASE has less than 1 GiB free"
}

discover_postgres_binaries() {
    local version bindir binary name

    PG_CONFIG="$(command -v pg_config)" || die "pg_config is unavailable"
    version="$(pg_run "$PG_CONFIG" --version)" || die "Unable to read pg_config version"
    is_postgres_16_version "$version" || die "PostgreSQL 16 pg_config is required"

    bindir="$(pg_run "$PG_CONFIG" --bindir)" || die "Unable to read PostgreSQL bindir"
    [[ "$bindir" == /* ]] || die "PostgreSQL bindir must be absolute"
    PG_BINDIR="$(realpath -e -- "$bindir")" || die "Unable to resolve PostgreSQL bindir"
    [[ -d "$PG_BINDIR" && ! -L "$PG_BINDIR" ]] || die "PostgreSQL bindir is unsafe"

    PG_INITDB="$PG_BINDIR/initdb"
    PG_POSTGRES="$PG_BINDIR/postgres"
    PG_CTL="$PG_BINDIR/pg_ctl"
    PG_ISREADY="$PG_BINDIR/pg_isready"
    PG_CREATEUSER="$PG_BINDIR/createuser"
    PG_CREATEDB="$PG_BINDIR/createdb"
    PG_PSQL="$PG_BINDIR/psql"

    for name in initdb postgres pg_ctl pg_isready createuser createdb psql; do
        binary="$PG_BINDIR/$name"
        [[ -f "$binary" && -x "$binary" && ! -L "$binary" ]] || die "Unsafe or missing PostgreSQL binary: $name"
        version="$(pg_run "$binary" --version)" || die "Unable to read version for PostgreSQL binary: $name"
        is_postgres_16_version "$version" || die "PostgreSQL binary is not major version 16: $name"
    done
}

preflight() {
    [[ "$(uname -s)" == "Linux" ]] || die "This runner only supports Linux"
    ((EUID == 0)) || die "This runner must be executed as root"

    local command_name
    for command_name in \
        awk basename chmod chown date df dirname find flock grep id mkdir mv paste pgrep realpath readlink \
        rm runuser sed sleep sort stat systemctl tail touch tr uname; do
        require_command "$command_name"
    done
    id postgres >/dev/null 2>&1 || die "The postgres operating-system user is unavailable"
    [[ -d /run/lock && ! -L /run/lock ]] || die "/run/lock is unavailable or unsafe"
    [[ "$(stat -c '%u' /run/lock)" == "0" ]] || die "/run/lock must be owned by root"
    if [[ -e "$LOCK_FILE" ]]; then
        [[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]] || die "Existing lock path is unsafe"
        [[ "$(stat -c '%u' "$LOCK_FILE")" == "0" ]] || die "Existing lock file must be owned by root"
    fi
    exec 9>"$LOCK_FILE"
    [[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]] || die "Lock file is unsafe"
    chmod 0600 "$LOCK_FILE"
    [[ "$(stat -c '%u' "$LOCK_FILE")" == "0" ]] || die "Lock file must be owned by root"
    flock -n 9 || die "Another native PostgreSQL test runner is active"

    [[ -d "$TEMP_BASE" && ! -L "$TEMP_BASE" ]] || die "$TEMP_BASE is unavailable or is a symbolic link"
    pg_run test -r "$TEMP_BASE" || die "The postgres user cannot read $TEMP_BASE"
    pg_run test -w "$TEMP_BASE" || die "The postgres user cannot write $TEMP_BASE"
    pg_run test -x "$TEMP_BASE" || die "The postgres user cannot traverse $TEMP_BASE"

    local script_dir
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
    BACK_ROOT="$(cd -- "$script_dir/.." && pwd -P)"
    PYTHON="$BACK_ROOT/.venv/bin/python"
    [[ -x "$PYTHON" ]] || die "Existing backend virtual environment is unavailable: $PYTHON"
    "$PYTHON" -B -c 'import pytest, psycopg, sqlalchemy' || die "Existing virtual environment lacks pytest, psycopg, or SQLAlchemy"

    check_free_space
    validate_production_data_root
    discover_postgres_binaries

    production_postgres_ready || die "Production PostgreSQL readiness check failed"
    BASELINE_PRODUCTION_PG_PID="$(production_postgres_pid)" || die "Unable to record production PostgreSQL PID"
    BASELINE_UVICORN_PIDS="$(capture_process_ids uvicorn)"
    BASELINE_NGINX_PIDS="$(capture_process_ids nginx)"
    [[ -n "$BASELINE_UVICORN_PIDS" ]] || die "Unable to record any Uvicorn PID"
    [[ -n "$BASELINE_NGINX_PIDS" ]] || die "Unable to record any Nginx PID"
    BASELINE_DATA_SUMMARY="$(summarize_data_root "$PRODUCTION_DATA_ROOT")" || die "Unable to obtain a complete production DATA_ROOT baseline"
    log "Safety baseline recorded without opening a production database session"
}

create_run_root() {
    local attempt
    for attempt in 1 2 3 4 5; do
        RUN_ID="$(generate_hex 16)" || die "Unable to generate run ID"
        validate_run_id "$RUN_ID" || die "Generated run ID is invalid"
        RUN_ROOT="$TEMP_BASE/viewer-pg16-test-$RUN_ID"
        if mkdir -m 0750 -- "$RUN_ROOT"; then
            break
        fi
        RUN_ROOT=""
    done
    [[ -n "$RUN_ROOT" ]] || die "Unable to create a unique test run directory"
    [[ ! -L "$RUN_ROOT" ]] || die "Test run directory must not be a symbolic link"
    chown root:postgres "$RUN_ROOT"

    PGDATA="$RUN_ROOT/data"
    SOCKET_DIR="$RUN_ROOT/socket"
    LOG_DIR="$RUN_ROOT/logs"
    MARKER_FILE="$RUN_ROOT/.viewer-pg16-test-owner"
    validate_runtime_paths || die "Generated runtime paths failed validation"

    TEST_ROLE="viewer_test_runner_$(generate_hex 8)"
    TEST_DATABASE="viewer_test_imports_$(generate_hex 8)"
    validate_role_name "$TEST_ROLE" || die "Generated test role name is invalid"
    validate_database_name "$TEST_DATABASE" || die "Generated test database name is invalid"

    {
        printf 'run_id=%s\n' "$RUN_ID"
        printf 'created_at=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        printf 'script_version=%s\n' "$SCRIPT_VERSION"
        printf 'expected_pg_major=%s\n' "$EXPECTED_PG_MAJOR"
    } >"$MARKER_FILE"
    chown root:root "$MARKER_FILE"
    chmod 0600 "$MARKER_FILE"

    mkdir -m 0750 -- "$LOG_DIR"
    chown postgres:postgres "$LOG_DIR"
    mkdir -m 0700 -- "$RUN_ROOT/pycache" "$RUN_ROOT/pytest" "$RUN_ROOT/pytest-non-pg" "$RUN_ROOT/viewer-data"
    log "Created isolated run directory: $RUN_ROOT"
}

choose_candidate_port() {
    local port
    port="$({
        "$PYTHON" -B - <<'PY'
import secrets
import socket

for _ in range(256):
    candidate = 20000 + secrets.randbelow(35001)
    if candidate in {5432, 50001, 50002}:
        continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind(("127.0.0.1", candidate))
        except OSError:
            continue
    print(candidate)
    raise SystemExit(0)
raise SystemExit(1)
PY
    })" || die "Unable to find an unused high TCP port"
    validate_port "$port" || die "Generated test port failed validation"
    printf '%s' "$port"
}

prepare_cluster_attempt() {
    local attempt="$1"
    local log_file="$LOG_DIR/postgres-attempt-$attempt.log"

    [[ "$attempt" =~ ^([1-9]|10)$ ]] || die "Invalid PostgreSQL start attempt"
    [[ ! -e "$PGDATA" && ! -e "$SOCKET_DIR" ]] || die "A fresh PGDATA and socket directory are required for every start attempt"
    validate_port "$TEST_PORT" || die "Refusing an unsafe PostgreSQL test port"

    mkdir -m 0700 -- "$PGDATA" "$SOCKET_DIR"
    chown postgres:postgres "$PGDATA" "$SOCKET_DIR"
    touch "$log_file"
    chown postgres:postgres "$log_file"
    chmod 0600 "$log_file"

    pg_run "$PG_INITDB" \
        --pgdata "$PGDATA" \
        --encoding UTF8 \
        --locale C \
        --auth-local reject \
        --auth-host reject \
        --no-instructions >/dev/null

    {
        printf 'local all postgres trust\n'
        printf 'local all all reject\n'
        printf 'local replication all reject\n'
        printf 'host %s %s 127.0.0.1/32 trust\n' "$TEST_DATABASE" "$TEST_ROLE"
        printf 'host all all 127.0.0.1/32 reject\n'
        printf 'host replication all 127.0.0.1/32 reject\n'
        printf 'host all all 0.0.0.0/0 reject\n'
        printf 'host replication all 0.0.0.0/0 reject\n'
        printf 'host all all ::0/0 reject\n'
        printf 'host replication all ::0/0 reject\n'
    } >"$PGDATA/pg_hba.conf"
    chown postgres:postgres "$PGDATA/pg_hba.conf"
    chmod 0600 "$PGDATA/pg_hba.conf"

    {
        printf "listen_addresses = '127.0.0.1'\n"
        printf 'port = %s\n' "$TEST_PORT"
        printf "unix_socket_directories = '%s'\n" "$SOCKET_DIR"
        printf 'unix_socket_permissions = 0700\n'
        printf 'logging_collector = off\n'
        printf 'fsync = off\n'
        printf 'synchronous_commit = off\n'
        printf 'full_page_writes = off\n'
        printf 'max_connections = 20\n'
    } >"$PGDATA/viewer-test.conf"
    chown postgres:postgres "$PGDATA/viewer-test.conf"
    chmod 0600 "$PGDATA/viewer-test.conf"
    printf "include = 'viewer-test.conf'\n" >>"$PGDATA/postgresql.conf"
    chown postgres:postgres "$PGDATA/postgresql.conf"
}

postmaster_pid_from_file() {
    local pid_file="$PGDATA/postmaster.pid"
    local pid
    [[ -f "$pid_file" && ! -L "$pid_file" ]] || return 1
    pid="$(sed -n '1p' "$pid_file")" || return 1
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    printf '%s' "$pid"
}

temporary_postmaster_is_running() {
    local pid
    pid="$(postmaster_pid_from_file)" || return 1
    kill -0 "$pid" 2>/dev/null
}

find_temporary_postmaster_pids() {
    local process_dir pid command_line process_executable postgres_real
    local matches=""

    [[ -n "$PGDATA" && -n "$PG_POSTGRES" ]] || return 1
    postgres_real="$(realpath -e -- "$PG_POSTGRES")" || return 1
    for process_dir in /proc/[0-9]*; do
        [[ -r "$process_dir/cmdline" && -e "$process_dir/exe" ]] || continue
        pid="${process_dir##*/}"
        [[ "$pid" =~ ^[1-9][0-9]*$ ]] || continue
        process_executable="$(readlink -f -- "$process_dir/exe" 2>/dev/null)" || continue
        [[ "$process_executable" == "$postgres_real" ]] || continue
        command_line="$(tr '\0' ' ' <"$process_dir/cmdline" 2>/dev/null)" || continue
        if [[ "$command_line" == *"-D $PGDATA"* || "$command_line" == *"--data-directory=$PGDATA"* ]]; then
            matches+="${matches:+,}$pid"
        fi
    done
    printf '%s' "$matches"
}

archive_failed_port_attempt() {
    local attempt="$1"
    local failed_data="$RUN_ROOT/failed-data-$attempt"
    local failed_socket="$RUN_ROOT/failed-socket-$attempt"

    local matching_processes
    matching_processes="$(find_temporary_postmaster_pids)" || die "Unable to scan for failed temporary PostgreSQL processes"
    [[ -z "$matching_processes" ]] || die "A failed temporary PostgreSQL process is still running; refusing retry"
    temporary_postmaster_is_running && die "A failed temporary PostgreSQL PID is still active; refusing retry"
    [[ -d "$PGDATA" && ! -L "$PGDATA" ]] || die "Failed PGDATA is unsafe"
    [[ -d "$SOCKET_DIR" && ! -L "$SOCKET_DIR" ]] || die "Failed socket directory is unsafe"
    [[ ! -e "$failed_data" && ! -e "$failed_socket" ]] || die "Failed-attempt archive path already exists"
    if [[ -e "$PGDATA/postmaster.pid" ]]; then
        [[ -f "$PGDATA/postmaster.pid" && ! -L "$PGDATA/postmaster.pid" ]] || die "Unsafe failed postmaster.pid"
        rm -f -- "$PGDATA/postmaster.pid"
    fi
    mv -- "$PGDATA" "$failed_data"
    mv -- "$SOCKET_DIR" "$failed_socket"
    log "Archived failed port attempt $attempt before selecting a new port"
}

start_temporary_postgres() {
    local attempt log_file
    for ((attempt = 1; attempt <= MAX_PORT_ATTEMPTS; attempt += 1)); do
        TEST_PORT="$(choose_candidate_port)"
        validate_port "$TEST_PORT" || die "Unsafe test port"
        prepare_cluster_attempt "$attempt"
        log_file="$LOG_DIR/postgres-attempt-$attempt.log"

        if pg_run "$PG_CTL" \
            --pgdata "$PGDATA" \
            --log "$log_file" \
            --wait \
            --timeout 20 \
            start; then
            temporary_postmaster_is_running || die "Temporary PostgreSQL reported success without a valid postmaster PID"
            pg_run "$PG_ISREADY" \
                --host "$SOCKET_DIR" \
                --port "$TEST_PORT" \
                --dbname postgres \
                --username postgres \
                --timeout 5 >/dev/null || die "Temporary PostgreSQL did not become ready"
            log "Temporary PostgreSQL 16 is ready on 127.0.0.1:$TEST_PORT"
            return 0
        fi

        if temporary_postmaster_is_running; then
            die "Temporary PostgreSQL start failed but its postmaster is still running"
        fi
        if grep -Eq 'Address already in use|could not bind.*127[.]0[.]0[.]1' "$log_file"; then
            archive_failed_port_attempt "$attempt"
            if ((attempt == MAX_PORT_ATTEMPTS)); then
                mkdir -m 0700 -- "$PGDATA" "$SOCKET_DIR"
                chown postgres:postgres "$PGDATA" "$SOCKET_DIR"
                return 1
            fi
            continue
        fi
        error "Temporary PostgreSQL failed for a reason other than a detected port collision"
        tail -n 50 "$log_file" >&2 || true
        return 1
    done
    die "Unable to start temporary PostgreSQL after $MAX_PORT_ATTEMPTS port attempts"
}

create_restricted_test_target() {
    local role_check database_owner

    validate_role_name "$TEST_ROLE" || die "Unsafe role name"
    validate_database_name "$TEST_DATABASE" || die "Unsafe database name"
    validate_port "$TEST_PORT" || die "Unsafe test port"

    pg_run "$PG_CREATEUSER" \
        --host "$SOCKET_DIR" \
        --port "$TEST_PORT" \
        --username postgres \
        --no-password \
        --login \
        --no-superuser \
        --no-createdb \
        --no-createrole \
        --inherit \
        --no-replication \
        --no-bypassrls \
        "$TEST_ROLE"

    pg_run "$PG_CREATEDB" \
        --host "$SOCKET_DIR" \
        --port "$TEST_PORT" \
        --username postgres \
        --no-password \
        --owner "$TEST_ROLE" \
        --encoding UTF8 \
        --template template0 \
        "$TEST_DATABASE"

    role_check="$(
        printf '%s\n' \
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls" \
            "FROM pg_roles WHERE rolname = :'role_name';" |
            pg_run "$PG_PSQL" \
                --host "$SOCKET_DIR" \
                --port "$TEST_PORT" \
                --username postgres \
                --dbname postgres \
                --no-password \
                --no-align \
                --tuples-only \
                --set ON_ERROR_STOP=1 \
                --set "role_name=$TEST_ROLE" \
                --file -
    )" || die "Unable to verify the temporary PostgreSQL role"
    role_check="$(printf '%s' "$role_check" | tr -d '[:space:]')"
    [[ "$role_check" == "t|f|f|f|f|f" ]] || die "Temporary PostgreSQL role permissions are not sufficiently restricted"

    database_owner="$(
        printf '%s\n' \
            "SELECT owner.rolname FROM pg_database AS db" \
            "JOIN pg_roles AS owner ON owner.oid = db.datdba" \
            "WHERE db.datname = :'database_name';" |
            pg_run "$PG_PSQL" \
                --host "$SOCKET_DIR" \
                --port "$TEST_PORT" \
                --username postgres \
                --dbname postgres \
                --no-password \
                --no-align \
                --tuples-only \
                --set ON_ERROR_STOP=1 \
                --set "database_name=$TEST_DATABASE" \
                --file -
    )" || die "Unable to verify the temporary PostgreSQL database owner"
    database_owner="$(printf '%s' "$database_owner" | tr -d '[:space:]')"
    [[ "$database_owner" == "$TEST_ROLE" ]] || die "Temporary test database is not owned by the restricted test role"
    log "Restricted test role and database ownership verified"
}

configure_test_environment() {
    mkdir -m 0700 -- "$RUN_ROOT/test-tmp"
    export VIEWER_ENV="test"
    export DATABASE_URL="sqlite+pysqlite:///$RUN_ROOT/viewer-test.sqlite"
    export DATA_ROOT="$RUN_ROOT/viewer-data"
    export VIEWER_TEST_POSTGRES_URL="postgresql+psycopg://$TEST_ROLE@127.0.0.1:$TEST_PORT/$TEST_DATABASE"
    export VIEWER_PRODUCTION_DATABASE_IDENTITY="$PRODUCTION_IDENTITY"
    export PYTHONPYCACHEPREFIX="$RUN_ROOT/pycache"
    export TMPDIR="$RUN_ROOT/test-tmp"
}

run_pytest_command() {
    local basetemp="$1"
    shift
    local result

    (
        cd "$BACK_ROOT"
        "$PYTHON" -B -m pytest \
            "$@" \
            -p no:cacheprovider \
            --basetemp "$basetemp"
    ) &
    PYTEST_PID=$!
    set +e
    wait "$PYTEST_PID"
    result=$?
    set -e
    PYTEST_PID=""
    return "$result"
}

run_tests() {
    log "Running PostgreSQL 16 capability tests"
    run_pytest_command "$RUN_ROOT/pytest" -m postgres --require-postgres || return $?

    if ((RUN_NON_POSTGRES)); then
        log "Running non-PostgreSQL regression tests"
        run_pytest_command "$RUN_ROOT/pytest-non-pg" -m "not postgres" || return $?
    fi
}

verify_postmaster_evidence() {
    local pid="$1"
    local pid_data command_line process_executable pgdata_real postgres_real

    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    [[ -r "/proc/$pid/cmdline" && -e "/proc/$pid/exe" ]] || return 1
    pgdata_real="$(realpath -e -- "$PGDATA")" || return 1
    postgres_real="$(realpath -e -- "$PG_POSTGRES")" || return 1
    pid_data="$(sed -n '2p' "$PGDATA/postmaster.pid")" || return 1
    [[ -n "$pid_data" ]] || return 1
    pid_data="$(realpath -e -- "$pid_data")" || return 1
    [[ "$pid_data" == "$pgdata_real" ]] || return 1
    process_executable="$(readlink -f -- "/proc/$pid/exe")" || return 1
    [[ "$process_executable" == "$postgres_real" ]] || return 1
    command_line="$(tr '\0' ' ' <"/proc/$pid/cmdline")" || return 1
    [[ "$command_line" == *"$postgres_real"* ]] || return 1
    [[ "$command_line" == *"-D $pgdata_real"* || "$command_line" == *"--data-directory=$pgdata_real"* ]]
}

wait_for_process_exit() {
    local pid="$1"
    local attempt
    for ((attempt = 0; attempt < 300; attempt += 1)); do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.1
    done
    return 1
}

stop_temporary_postgres() {
    local pid="" matching_processes=""
    [[ -n "$PGDATA" && -d "$PGDATA" && ! -L "$PGDATA" ]] || return 0
    pid="$(postmaster_pid_from_file)" || true
    if [[ -z "$pid" ]]; then
        matching_processes="$(find_temporary_postmaster_pids)" || return 1
        if [[ -n "$matching_processes" ]]; then
            error "Temporary postgres process exists without a usable postmaster.pid; refusing an unproven stop"
            return 1
        fi
        return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    if pg_run "$PG_CTL" --pgdata "$PGDATA" --mode fast --wait --timeout 30 stop; then
        wait_for_process_exit "$pid" || return 1
        return 0
    fi

    if ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    verify_postmaster_evidence "$pid" || {
        error "Fast stop failed and postmaster ownership evidence is insufficient; refusing immediate stop"
        return 1
    }
    error "Fast stop failed; using immediate stop only for the proven temporary postmaster PID $pid"
    pg_run "$PG_CTL" --pgdata "$PGDATA" --mode immediate --wait --timeout 30 stop || return 1
    wait_for_process_exit "$pid"
}

port_is_released() {
    validate_port "$1" || return 1
    "$PYTHON" -B - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    probe.bind(("127.0.0.1", port))
PY
}

stop_pytest_if_needed() {
    local pid="$PYTEST_PID"
    local attempt
    [[ -n "$pid" && "$pid" =~ ^[1-9][0-9]*$ ]] || return 0
    kill -0 "$pid" 2>/dev/null || return 0
    kill -TERM "$pid" 2>/dev/null || true
    for ((attempt = 0; attempt < 100; attempt += 1)); do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.1
    done
    kill -KILL "$pid" 2>/dev/null || true
    wait_for_process_exit "$pid"
}

verify_production_baseline() {
    local current_pg_pid current_uvicorn_pids current_nginx_pids current_data_summary
    production_postgres_ready || {
        error "Production PostgreSQL readiness changed during the test run"
        return 1
    }
    current_pg_pid="$(production_postgres_pid)" || {
        error "Unable to re-read production PostgreSQL PID"
        return 1
    }
    current_uvicorn_pids="$(capture_process_ids uvicorn)"
    current_nginx_pids="$(capture_process_ids nginx)"
    current_data_summary="$(summarize_data_root "$PRODUCTION_DATA_ROOT")" || {
        error "Unable to obtain a complete post-test production DATA_ROOT summary"
        return 1
    }

    [[ "$current_pg_pid" == "$BASELINE_PRODUCTION_PG_PID" ]] || {
        error "Production PostgreSQL PID changed; the runner will not attempt repair"
        return 1
    }
    [[ "$current_uvicorn_pids" == "$BASELINE_UVICORN_PIDS" ]] || {
        error "Uvicorn PID set changed; the runner will not attempt repair"
        return 1
    }
    [[ "$current_nginx_pids" == "$BASELINE_NGINX_PIDS" ]] || {
        error "Nginx PID set changed; the runner will not attempt repair"
        return 1
    }
    [[ "$current_data_summary" == "$BASELINE_DATA_SUMMARY" ]] || {
        error "Production DATA_ROOT metadata summary changed"
        return 1
    }
    return 0
}

validate_deletion_target() {
    local run_real pgdata_real marker_run_id marker_owner

    validate_runtime_paths || return 1
    [[ -d "$RUN_ROOT" && ! -L "$RUN_ROOT" ]] || return 1
    run_real="$(realpath -e -- "$RUN_ROOT")" || return 1
    [[ "$run_real" == "$TEMP_BASE/viewer-pg16-test-$RUN_ID" ]] || return 1
    [[ "$(basename -- "$run_real")" =~ ^viewer-pg16-test-[0-9a-f]{32}$ ]] || return 1
    [[ "$run_real" != "$TEMP_BASE" ]] || return 1
    [[ "$(stat -c '%u' "$run_real")" == "0" ]] || return 1

    [[ -f "$MARKER_FILE" && ! -L "$MARKER_FILE" ]] || return 1
    marker_owner="$(stat -c '%u' "$MARKER_FILE")" || return 1
    [[ "$marker_owner" == "0" ]] || return 1
    marker_run_id="$(sed -n 's/^run_id=//p' "$MARKER_FILE")" || return 1
    [[ "$marker_run_id" == "$RUN_ID" ]] || return 1

    [[ -d "$PGDATA" && ! -L "$PGDATA" ]] || return 1
    pgdata_real="$(realpath -e -- "$PGDATA")" || return 1
    [[ "$pgdata_real" == "$run_real/data" ]] || return 1
    [[ "$pgdata_real" == "$run_real"/* ]]
}

cleanup() {
    local requested_status="$1"
    local final_status="$requested_status"

    if ((CLEANUP_STARTED)); then
        exit "$final_status"
    fi
    CLEANUP_STARTED=1
    trap - EXIT INT TERM HUP
    set +e

    log "Cleanup started"
    stop_pytest_if_needed || {
        error "Unable to stop the pytest subprocess"
        CLEANUP_FAILED=1
        DELETE_ALLOWED=0
    }

    stop_temporary_postgres || {
        error "Unable to prove that the temporary PostgreSQL process stopped"
        CLEANUP_FAILED=1
        DELETE_ALLOWED=0
    }

    if [[ -n "$TEST_PORT" ]]; then
        port_is_released "$TEST_PORT" || {
            error "Temporary PostgreSQL port was not released"
            CLEANUP_FAILED=1
            DELETE_ALLOWED=0
        }
    fi

    if [[ -n "$BASELINE_PRODUCTION_PG_PID" ]]; then
        verify_production_baseline || CLEANUP_FAILED=1
    fi

    if [[ -n "$RUN_ROOT" && -e "$RUN_ROOT" ]]; then
        if ((DELETE_ALLOWED)) && validate_deletion_target; then
            rm -rf --one-file-system -- "$RUN_ROOT"
            if [[ -e "$RUN_ROOT" ]]; then
                error "Temporary run directory could not be removed: $RUN_ROOT"
                CLEANUP_FAILED=1
            else
                log "Temporary run directory removed"
            fi
        else
            error "Deletion safety proof failed; residual path retained: $RUN_ROOT"
            CLEANUP_FAILED=1
        fi
    fi

    if ((CLEANUP_FAILED)); then
        final_status=1
        error "Cleanup or safety-baseline verification failed"
    else
        log "Cleanup and production safety-baseline verification completed"
    fi
    exit "$final_status"
}

trap 'cleanup $?' EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM
trap 'cleanup 129' HUP

main() {
    parse_arguments "$@"
    preflight
    create_run_root
    start_temporary_postgres
    create_restricted_test_target
    configure_test_environment
    run_tests
    log "Requested test suites completed successfully"
}

main "$@"
