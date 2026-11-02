"""Exercise dataset imports against a running WebUI and disposable Postgres.

Run inside the web image (which supplies openpyxl) or its development environment.
The caller must provision public.web_import_smoke with columns id/name and rows
(1, 'Ada'), (2, 'Grace'), readable by the supplied database account.
"""
from __future__ import annotations

import argparse
import io
import json
import urllib.error
import urllib.request
import uuid

from openpyxl import Workbook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5050')
    parser.add_argument('--token', required=True)
    parser.add_argument('--db-host', required=True)
    parser.add_argument('--db-port', type=int, default=5432)
    parser.add_argument('--db-user', default='web_reader')
    parser.add_argument('--db-password', required=True)
    parser.add_argument('--db-name', default='postgres')
    args = parser.parse_args()

    def request(method, path, payload=None, *, dataset=None, upload=None, authenticated=True):
        headers = {'Authorization': f'Bearer {args.token}'} if authenticated else {}
        if dataset:
            headers['X-Goldenmatch-Dataset'] = dataset
        body = None
        if upload:
            filename, content = upload
            boundary = f'smoke-{uuid.uuid4().hex}'
            headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
            ).encode() + content + f'\r\n--{boundary}--\r\n'.encode()
        elif payload is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(payload).encode()
        req = urllib.request.Request(args.url + '/api/v1' + path, body, headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def ok(method, path, payload=None, **kwargs):
        status, result = request(method, path, payload, **kwargs)
        assert 200 <= status < 300, (method, path, status, result)
        return result

    for path in ('/datasets', '/connections'):
        status, _ = request('GET', path, authenticated=False)
        assert status == 401, (path, status)

    csv_stage = ok('POST', '/datasets/uploads', upload=('contacts.csv', b'id,name\n1,Ada\n2,Grace\n'))
    preview = ok('POST', f"/datasets/uploads/{csv_stage['upload_id']}/preview", {})
    assert preview['columns'] == ['id', 'name'], preview
    assert [[str(cell) for cell in row] for row in preview['rows']] == [['1', 'Ada'], ['2', 'Grace']], preview
    first = ok('POST', f"/datasets/uploads/{csv_stage['upload_id']}/import", {'name': 'CSV smoke'})

    workbook = Workbook()
    workbook.active.title = 'Ignore'
    workbook.active.append(['wrong'])
    workbook.active.append(['not imported'])
    selected = workbook.create_sheet('Contacts')
    selected.append(['id', 'name'])
    selected.append([3, 'Lin'])
    selected.append([4, 'Sam'])
    stream = io.BytesIO()
    workbook.save(stream)
    excel_stage = ok('POST', '/datasets/uploads', upload=('contacts.xlsx', stream.getvalue()))
    assert 'Contacts' in excel_stage['sheets'], excel_stage
    preview = ok('POST', f"/datasets/uploads/{excel_stage['upload_id']}/preview", {'sheet': 'Contacts'})
    assert [[str(cell) for cell in row] for row in preview['rows']] == [['3', 'Lin'], ['4', 'Sam']], preview
    second = ok('POST', f"/datasets/uploads/{excel_stage['upload_id']}/import", {'name': 'Excel smoke', 'sheet': 'Contacts'})
    assert first['id'] != second['id'], (first, second)

    rules = {'threshold': 0.8, 'matchkeys': [
        {'column': 'name', 'scorer': 'exact', 'weight': 1.0, 'transforms': []},
    ]}
    run = ok('POST', '/run', {'rules': rules}, dataset=first['id'])
    label = {'row_id_a': 0, 'row_id_b': 1, 'label': 'non_match', 'run_name': run['run_name']}
    saved_label = ok('POST', '/labels', label, dataset=first['id'])
    assert saved_label['mirrored'] is True, saved_label
    assert ok('GET', '/labels', dataset=second['id']) == []
    labels = ok('GET', '/labels', dataset=first['id'])
    assert [(item['row_id_a'], item['row_id_b'], item['label']) for item in labels] == [(0, 1, 'non_match')], labels
    corrections = ok('GET', '/memory/corrections', dataset=first['id'])['items']
    assert [(item['id_a'], item['id_b'], item['decision']) for item in corrections] == [(0, 1, 'reject')], corrections
    assert ok('GET', '/memory/corrections', dataset=second['id'])['items'] == []
    assert ok('GET', '/memory/stats', dataset=second['id'])['count'] == 0
    for dataset in (first, second):
        project = ok('GET', '/project', dataset=dataset['id'])
        assert project['dataset_id'] == dataset['id'], project
    before_failure = {item['id'] for item in ok('GET', '/datasets')['items']}
    invalid_stage = ok('POST', '/datasets/uploads', upload=('invalid.csv', b'id,name\n1,Ada,extra\n'))
    status, _ = request('POST', f"/datasets/uploads/{invalid_stage['upload_id']}/import", {'name': 'Invalid'})
    assert status == 400, status
    assert {item['id'] for item in ok('GET', '/datasets')['items']} == before_failure
    assert ok('GET', '/project', dataset=first['id'])['dataset_id'] == first['id']

    connection = ok('POST', '/connections', {
        'name': 'Postgres smoke', 'host': args.db_host, 'port': args.db_port,
        'database': args.db_name, 'username': args.db_user,
        'password': args.db_password, 'sslmode': 'disable',
    })
    connection_id = connection['id']
    try:
        assert connection['has_password'] is True, connection
        assert args.db_password not in json.dumps(ok('GET', '/connections'))
        assert ok('POST', f'/connections/{connection_id}/test')['ok'] is True
        # Editing non-secret fields must preserve the usable saved password.
        updated = {key: value for key, value in connection.items() if key not in {'id', 'has_password'}}
        updated['name'] = 'Renamed Postgres smoke'
        ok('PUT', f'/connections/{connection_id}', updated)
        assert ok('POST', f'/connections/{connection_id}/test')['ok'] is True
        tables = ok('GET', f'/connections/{connection_id}/tables')['items']
        assert {'schema': 'public', 'name': 'web_import_smoke'} in tables, tables
        selection = {'schema': 'public', 'table': 'web_import_smoke'}
        preview = ok('POST', f'/connections/{connection_id}/preview', selection)
        actual = sorted([str(cell) for cell in row] for row in preview['rows'])
        assert actual == [['1', 'Ada'], ['2', 'Grace']], preview
        imported = ok('POST', f'/connections/{connection_id}/import', {**selection, 'name': 'Database smoke'})
        assert imported['row_count'] == 2, imported
        assert imported['id'] not in (first['id'], second['id']), imported
        assert ok('GET', '/labels', dataset=imported['id']) == []
    finally:
        ok('DELETE', f'/connections/{connection_id}')
    print('PASS: authenticated CSV/XLSX imports, worksheet selection, dataset label isolation, Postgres connection/test/table preview/snapshot import and secret redaction')


if __name__ == '__main__':
    main()
