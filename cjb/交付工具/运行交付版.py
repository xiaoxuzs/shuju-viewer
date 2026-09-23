"""Windows x64 launcher; only manages this package's database and child processes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime'
PGDATA = STATE / 'postgres'
PGBIN = ROOT / 'runtime/postgresql/bin'
PYTHON = ROOT / 'runtime/python/python.exe'
NODE = ROOT / 'runtime/node/node.exe'


def configuration():
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url
    values = {k: v for k, v in dotenv_values(ROOT / 'back/.env').items() if v is not None}
    url = make_url(values['DATABASE_URL'])
    if (url.get_backend_name() != 'postgresql' or url.host != '127.0.0.1' or not url.port
            or url.port == 5432 or url.database != 'Viewer_Delivery'
            or url.username != 'viewer_delivery' or not url.password):
        raise RuntimeError('Keep the dedicated local Viewer_Delivery database and non-5432 port in back/.env.')
    return values, url


def environment(api_port=18000):
    values, _ = configuration()
    env = os.environ.copy()
    prefixes = ('PG', 'PYTHON', 'VIRTUAL_ENV', 'VIEWER_', 'ZP_', 'RAW_', 'AGENT_',
                'BU_', 'IMPORT_', 'PFMB_', 'MOONSHOT_', 'DEEPSEEK_', 'API_', 'THERMO_')
    for key in list(env):
        if key.startswith(prefixes) or key in ('DATABASE_URL', 'DATA_ROOT', 'LOG_LEVEL', 'SPECTRUM_CACHE_SIZE'):
            env.pop(key)
    env.update(values)
    windows = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env['PATH'] = os.pathsep.join(str(p) for p in (ROOT / 'runtime/node', ROOT / 'runtime/tools',
        ROOT / 'runtime/python', PGBIN, ROOT / 'ThermoRawFileParser1.4.5', windows / 'System32', windows))
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', VIEWER_ENV='development',
               VIEWER_API_TARGET=f'http://127.0.0.1:{api_port}')
    for key in ('THERMO_RAW_FILE_PARSER_EXE', 'ZP_WORKER_PYTHON'):
        if env.get(key):
            p = Path(env[key])
            env[key] = str(p if p.is_absolute() else (ROOT / 'back' / p).resolve())
    return env


def pg_environment():
    _, url = configuration()
    env = environment()
    env.update(PGHOST='127.0.0.1', PGPORT=str(url.port), PGUSER=url.username,
               PGPASSWORD=url.password, PGDATABASE='postgres', PGCLIENTENCODING='UTF8')
    return env


def run_tool(args, *, env=None, timeout=60):
    # pg_ctl's detached Windows server can inherit pipe handles. A regular temporary
    # file avoids communicate() waiting for the entire server lifetime after pg_ctl exits.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run([str(a) for a in args], env=env or environment(), cwd=ROOT,
                                stdout=output, stderr=subprocess.STDOUT,
                                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        output.seek(0)
        message = output.read().decode('utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed ({result.returncode}):\n{message}')
    return message


def check_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is occupied. No existing process will be stopped.') from exc


def ensure_state():
    STATE.mkdir(exist_ok=True)
    if STATE.resolve().parent != ROOT or (PGDATA.exists() and PGDATA.resolve().parent != STATE):
        raise RuntimeError('Runtime directories must not link outside this package.')
    (STATE / 'logs').mkdir(exist_ok=True)


@contextmanager
def exclusive_lock():
    import msvcrt
    ensure_state()
    with (STATE / 'launcher.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('This delivery is already running. Use stop-all.bat first.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def stop_database():
    if (PGDATA / 'postmaster.pid').exists():
        run_tool([PGBIN / 'pg_ctl.exe', '-D', PGDATA, '-m', 'fast', '-w', '-t', '30', 'stop'], env=pg_environment())


def start_database():
    import psycopg
    from psycopg import sql
    ensure_state()
    _, url = configuration()
    check_port(url.port)
    if not (PGDATA / 'PG_VERSION').is_file():
        if PGDATA.exists() and any(PGDATA.iterdir()):
            raise RuntimeError('Incomplete database initialization; existing files will not be deleted.')
        password_file = STATE / 'init-password.tmp'
        try:
            password_file.write_text(url.password + '\n', encoding='utf-8')
            run_tool([PGBIN / 'initdb.exe', '-D', PGDATA, '-U', url.username, '--auth=scram-sha-256',
                      '--encoding=UTF8', '--locale=C', '--pwfile', password_file], env=pg_environment())
        finally:
            password_file.unlink(missing_ok=True)
    run_tool([PGBIN / 'pg_ctl.exe', '-D', PGDATA, '-l', STATE / 'logs/postgresql.log',
              '-o', f'-h 127.0.0.1 -p {url.port}', '-w', '-t', '30', 'start'], env=pg_environment())
    connect = dict(host='127.0.0.1', port=url.port, user=url.username, password=url.password)
    try:
        with psycopg.connect(**connect, dbname='postgres', autocommit=True) as conn:
            actual = Path(conn.execute('SHOW data_directory').fetchone()[0]).resolve()
            if actual != PGDATA.resolve():
                raise RuntimeError('Database directory mismatch. No schema will be written.')
            if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (url.database,)).fetchone():
                conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(url.database)))
        with psycopg.connect(**connect, dbname=url.database) as conn:
            tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        if not tables:
            env = pg_environment()
            env['PGDATABASE'] = url.database
            run_tool([PGBIN / 'psql.exe', '-X', '--single-transaction', '-v', 'ON_ERROR_STOP=1',
                      '-f', ROOT / '数据库/空库结构.sql'], env=env)
        expected = json.loads((ROOT / '交付清单/数据库与配置清单.json').read_text(encoding='utf-8'))['tables']
        with psycopg.connect(**connect, dbname=url.database) as conn:
            actual_tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        if not set(expected).issubset(actual_tables):
            raise RuntimeError('Incomplete delivery schema. Existing tables will not be overwritten.')
        print(f'Database ready: 127.0.0.1:{url.port} / {url.database}', flush=True)
    except BaseException:
        stop_database()
        raise


def check_runtime():
    if os.name != 'nt' or sys.maxsize <= 2**32:
        raise RuntimeError('This package contains Windows x64 runtimes only.')
    for p in (PYTHON, NODE, PGBIN / 'initdb.exe', ROOT / 'front/node_modules/vite/bin/vite.js',
              ROOT / 'back/vendor/zp_engine/binary_layer/__init__.py', ROOT / '数据库/空库结构.sql'):
        if not p.is_file():
            raise RuntimeError(f'Missing delivery file: {p.relative_to(ROOT)}')
    code = 'import fastapi,uvicorn,sqlalchemy,psycopg,pyarrow,numpy,lxml,tkinter,langgraph.checkpoint.postgres; print("Python dependencies OK")'
    print(run_tool([PYTHON, '-B', '-c', code]).strip(), flush=True)
    print('Node ' + run_tool([NODE, '--version']).strip(), flush=True)
    print(run_tool([PGBIN / 'postgres.exe', '--version']).strip(), flush=True)
    print('Delivery runtime and configuration checks OK.', flush=True)


def wait_http(url, process):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Service exited; see .runtime/logs.')
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f'Service startup timed out: {url}')


def terminate_child(process):
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
        process.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        process.wait(timeout=10)


def serve(args):
    with exclusive_lock():
        check_port(args.api_port)
        if args.command == 'run':
            check_port(args.front_port)
        check_runtime()
        (ROOT / 'shuju').mkdir(exist_ok=True)
        stop_file = STATE / 'stop.request'
        stop_file.unlink(missing_ok=True)
        children, streams = [], []
        started = False
        try:
            start_database()
            started = True
            commands = [('backend', [str(PYTHON), '-B', '-m', 'uvicorn', 'app.main:app', '--host',
                          '127.0.0.1', '--port', str(args.api_port)], ROOT / 'back',
                          f'http://127.0.0.1:{args.api_port}/health')]
            if args.command == 'run':
                commands.append(('frontend', [str(NODE), str(ROOT / 'front/node_modules/vite/bin/vite.js'),
                                 '--host', '127.0.0.1', '--port', str(args.front_port), '--strictPort'],
                                 ROOT / 'front', f'http://127.0.0.1:{args.front_port}'))
            for name, command, cwd, url in commands:
                stream = (STATE / f'logs/{name}.log').open('ab')
                streams.append(stream)
                child = subprocess.Popen(command, cwd=cwd, env=environment(args.api_port), stdout=stream,
                                          stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                children.append(child)
                wait_http(url, child)
                print(f'{name}: {url}', flush=True)
            print('READY. Keep this window open. Ctrl+C or stop-all.bat stops this delivery only.', flush=True)
            while not stop_file.exists():
                if any(p.poll() is not None for p in children):
                    raise RuntimeError('A service stopped unexpectedly; see .runtime/logs.')
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('Stopping delivery...', flush=True)
        finally:
            for child in reversed(children):
                terminate_child(child)
            for stream in streams:
                stream.close()
            if started:
                stop_database()
            stop_file.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'backend', 'frontend', 'database', 'check', 'stop', 'stop-database'))
    parser.add_argument('--api-port', type=int, default=18000)
    parser.add_argument('--front-port', type=int, default=15173)
    args = parser.parse_args()
    if args.command == 'check':
        check_runtime()
    elif args.command == 'stop':
        ensure_state()
        (STATE / 'stop.request').write_text('stop\n', encoding='utf-8')
        print('Stop requested. Wait for the launch window to finish.')
    elif args.command in ('database', 'stop-database'):
        with exclusive_lock():
            if args.command == 'database':
                check_runtime()
                start_database()
            stop_database()
    elif args.command == 'frontend':
        check_port(args.front_port)
        check_runtime()
        child = subprocess.Popen([str(NODE), str(ROOT / 'front/node_modules/vite/bin/vite.js'), '--host',
                                  '127.0.0.1', '--port', str(args.front_port), '--strictPort'],
                                 cwd=ROOT / 'front', env=environment(args.api_port),
                                 creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            child.wait()
        except KeyboardInterrupt:
            terminate_child(child)
    else:
        serve(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(1)
