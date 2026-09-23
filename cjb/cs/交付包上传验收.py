"""Exercise a relocated, disposable delivery only; never the shipped or original DB."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import time

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg import sql
from sqlalchemy.engine import make_url


def synthetic_mzml() -> bytes:
    def array(values, accession, name):
        binary = base64.b64encode(struct.pack('<' + 'd' * len(values), *values)).decode()
        return (f'<binaryDataArray encodedLength="{len(binary)}"><cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/>'
                f'<cvParam cvRef="MS" accession="MS:1000576" name="no compression"/>'
                f'<cvParam cvRef="MS" accession="{accession}" name="{name}"/><binary>{binary}</binary></binaryDataArray>')
    prefix = '''<?xml version="1.0" encoding="UTF-8"?>
<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML version="1.1.0" id="delivery-smoke">
<cvList count="2"><cv id="MS" fullName="PSI-MS" version="4.1" URI="https://example.invalid/ms.obo"/><cv id="UO" fullName="Unit Ontology" version="1" URI="https://example.invalid/uo.obo"/></cvList>
<fileDescription><fileContent><cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum"/><cvParam cvRef="MS" accession="MS:1000580" name="MSn spectrum"/></fileContent>
<sourceFileList count="1"><sourceFile id="source1" name="synthetic.raw" location="file:///synthetic"><cvParam cvRef="MS" accession="MS:1000768" name="Thermo nativeID format"/></sourceFile></sourceFileList></fileDescription>
<run id="delivery"><spectrumList count="2">'''.encode()
    document = prefix
    offsets = []
    for index in range(2):
        scan = index + 1
        native_id = f'controllerType=0 controllerNumber=1 scan={scan}'
        offsets.append((native_id, len(document)))
        spectrum = (f'<spectrum index="{index}" id="{native_id}" defaultArrayLength="3">'
                    f'<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{scan}"/>'
                    '<cvParam cvRef="MS" accession="MS:1000127" name="centroid spectrum"/>'
                    '<cvParam cvRef="MS" accession="MS:1000130" name="positive scan"/>'
                    f'<scanList count="1"><scan><cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{60 + index}" unitCvRef="UO" unitAccession="UO:0000010" unitName="second"/></scan></scanList>')
        if index:
            spectrum += ('<precursorList count="1"><precursor spectrumRef="controllerType=0 controllerNumber=1 scan=1">'
                         '<selectedIonList count="1"><selectedIon><cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="500"/>'
                         '<cvParam cvRef="MS" accession="MS:1000042" name="peak intensity" value="30"/>'
                         '<cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="2"/></selectedIon></selectedIonList>'
                         '<activation><cvParam cvRef="MS" accession="MS:1000133" name="collision-induced dissociation"/></activation></precursor></precursorList>')
        spectrum += '<binaryDataArrayList count="2">' + array([100, 200, 500], 'MS:1000514', 'm/z array')
        spectrum += array([10, 20, 30], 'MS:1000515', 'intensity array') + '</binaryDataArrayList></spectrum>'
        document += spectrum.encode()
    document += b'</spectrumList></run></mzML>'
    index_offset = len(document)
    document += ('<indexList count="1"><index name="spectrum">' + ''.join(
        f'<offset idRef="{native}">{offset}</offset>' for native, offset in offsets) +
        f'</index></indexList><indexListOffset>{index_offset}</indexListOffset><fileChecksum>').encode()
    document += hashlib.sha1(document).hexdigest().encode() + b'</fileChecksum></indexedmzML>'
    return document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:15173')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.parent.name.startswith('viewer-cjb-check-'):
        raise SystemExit('Only disposable viewer-cjb-check-* relocation directories are allowed.')
    url = make_url(dotenv_values(root / 'back/.env')['DATABASE_URL'])
    if url.host != '127.0.0.1' or url.port == 5432 or url.database != 'Viewer_Delivery':
        raise SystemExit('Not the isolated delivery database.')
    connect = dict(host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database)
    report = {'relocated_root': str(root), 'source_data_used': False}
    with psycopg.connect(**connect, options='-c default_transaction_read_only=on') as conn:
        assert Path(conn.execute('SHOW data_directory').fetchone()[0]).resolve() == root / '.runtime/postgres'
        tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        counts = {table: conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0] for table in tables}
    assert all(count == 0 for table, count in counts.items() if table != 'checkpoint_migrations'), counts
    report['initial_table_counts'] = counts
    with httpx.Client(base_url=args.base_url, timeout=30, trust_env=False) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        assert request('GET', '/api/v1/datasets') == []
        created = request('POST', '/api/v1/import-uploads', json={'import_type': 'TD_MZML'})
        upload_id = created['upload_id']
        payload = synthetic_mzml()
        uploaded = request('PUT', f'/api/v1/import-uploads/{upload_id}/files',
                           params={'relative_path': 'synthetic.mzML'}, content=payload,
                           headers={'content-type': 'application/octet-stream'})
        assert uploaded['size_bytes'] == len(payload)
        started = request('POST', f'/api/v1/import-uploads/{upload_id}/start',
                          json={'parameters': {'slug': 'delivery-smoke', 'name': 'Delivery smoke (synthetic)'}})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = request('GET', f"/api/v1/imports/{started['job_id']}")
            if job['status'] in ('success', 'failed'):
                break
            time.sleep(1)
        assert job['status'] == 'success', job
        datasets = request('GET', '/api/v1/datasets')
        assert len(datasets) == 1 and datasets[0]['slug'] == 'delivery-smoke', datasets
        report['upload_job'] = {k: job.get(k) for k in ('status', 'stage', 'progress')}
        with psycopg.connect(**connect, options='-c default_transaction_read_only=on') as conn:
            dataset_id, run_id = conn.execute('SELECT dataset_id, run_id FROM runs').fetchone()
            asset_path = conn.execute("SELECT zp_path FROM dataset_zp_assets WHERE status='active'").fetchone()[0]
        assert Path(asset_path).is_relative_to(root / 'shuju')
        spectrum = request('GET', f'/api/v1/datasets/{dataset_id}/runs/{run_id}/spectra/1')
        report['spectrum_response_keys'] = list(spectrum)
        report['active_zp_under_delivery_data_root'] = True
        report['result'] = 'passed'
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
