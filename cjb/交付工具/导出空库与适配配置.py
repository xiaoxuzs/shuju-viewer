"""One-time builder: read-only schema export; no business records or original edits."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

import psycopg
from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect', action='store_true')
    args = parser.parse_args()
    if SOURCE != Path('E:/viewer') or ROOT.name != 'cjb':
        raise SystemExit('Builder only runs against the original E:/viewer snapshot.')
    original = dotenv_values(SOURCE / 'back/.env')
    url = make_url(original['DATABASE_URL'])
    with psycopg.connect(host=url.host, port=url.port or 5432, dbname=url.database,
                          user=url.username, password=url.password, connect_timeout=10,
                          options='-c default_transaction_read_only=on') as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        version = conn.execute('SHOW server_version').fetchone()[0]
    print(json.dumps({'tables': tables, 'server_version': version, 'config_keys': list(original)}, ensure_ascii=False))
    if args.inspect:
        return
    output = ROOT / '数据库/空库结构.sql'
    if output.exists():
        raise SystemExit('Schema already exported; refusing to replace an existing snapshot.')
    child_env = os.environ.copy()
    child_env.update(PGHOST=url.host or 'localhost', PGPORT=str(url.port or 5432),
                     PGUSER=url.username or '', PGPASSWORD=url.password or '',
                     PGDATABASE=url.database or '', PGCLIENTENCODING='UTF8',
                     PGOPTIONS='-c default_transaction_read_only=on')
    subprocess.run([str(ROOT / 'runtime/postgresql/bin/pg_dump.exe'), '--schema-only',
                    '--schema=public', '--no-owner', '--no-privileges', '--no-tablespaces',
                    '--lock-wait-timeout=10000', '--file', str(output)],
                   env=child_env, check=True, timeout=90)
    sql = output.read_text(encoding='utf-8')
    sql = sql.replace('CREATE SCHEMA public;', 'CREATE SCHEMA IF NOT EXISTS public;')
    output.write_text(sql, encoding='utf-8')
    if re.search(r'(?im)^\s*(?:COPY\s|INSERT\s+INTO\s|SELECT\s+pg_catalog\.setval)', sql):
        raise RuntimeError('Schema export unexpectedly contains record/sequence-state statements.')
    database_url = URL.create('postgresql+psycopg', username='viewer_delivery',
                              password=secrets.token_urlsafe(24), host='127.0.0.1',
                              port=55432, database='Viewer_Delivery').render_as_string(hide_password=False)
    replacements = {
        'DATABASE_URL': database_url,
        'DATA_ROOT': '../shuju',
        'BU_DEFAULT_FASTA_PATH': '',
        'ZP_ALLOWED_SOURCE_ROOTS': '',
        'ZP_ENGINE_PATH': 'vendor/zp_engine',
        'ZP_WORKER_PYTHON': '../runtime/python/python.exe',
        'ZP_WORKER_PYTHONPATH': '',
        'THERMO_RAW_FILE_PARSER_EXE': '../ThermoRawFileParser1.4.5/ThermoRawFileParser.exe',
    }
    original_text = (SOURCE / 'back/.env').read_text(encoding='utf-8-sig')
    lines = original_text.splitlines()
    seen = set()
    result = []
    for line in lines:
        match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
        name = match.group(1).upper() if match else ''
        if name in replacements:
            if name not in seen:
                result.append(f'{name}={replacements[name]}')
            seen.add(name)
        else:
            result.append(line)
    result.extend(f'{name}={value}' for name, value in replacements.items() if name not in seen)
    (ROOT / 'back/.env').write_text('\n'.join(result) + '\n', encoding='utf-8')
    copied = dotenv_values(ROOT / 'back/.env')
    for key, value in original.items():
        if key.upper() not in replacements and copied.get(key) != value:
            raise RuntimeError(f'Configuration was not preserved: {key}')
    report = {'source_server_version': version, 'schema_only': True,
              'tables': tables, 'business_records_exported': 0,
              'adjusted_config_keys': list(replacements),
              'preserved_config_keys': [k for k in original if k.upper() not in replacements]}
    (ROOT / '交付清单/数据库与配置清单.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Schema exported without records. Configuration adapted; secret values are not printed.')


if __name__ == '__main__':
    main()
