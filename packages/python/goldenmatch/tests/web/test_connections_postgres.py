from __future__ import annotations

from urllib.parse import unquote, urlparse

import pytest

from .._pg_helpers import pg_url_fixture


@pytest.fixture
def postgres_url():
    yield from pg_url_fixture()


def test_saved_connection_reads_tables_previews_imports_without_writes_and_rejects_over_limit(
    client, postgres_url, monkeypatch
):
    psycopg = pytest.importorskip("psycopg")
    Fernet = pytest.importorskip("cryptography.fernet").Fernet
    from goldenmatch.web import connections

    parsed = urlparse(postgres_url.url())
    monkeypatch.setenv("GOLDENMATCH_WEB_ALLOWED_DB_HOSTS", parsed.hostname or "")
    monkeypatch.setenv("GOLDENMATCH_CONNECTION_KEY", Fernet.generate_key().decode())
    with psycopg.connect(postgres_url.url()) as conn:
        conn.execute("CREATE TABLE import_source (id integer, label text)")
        conn.execute("INSERT INTO import_source VALUES (1, 'Ada'), (2, 'Grace')")

    profile = client.post(
        "/api/v1/connections",
        json={
            "name": "Local test DB",
            "host": parsed.hostname,
            "port": parsed.port,
            "database": unquote(parsed.path.lstrip("/")),
            "username": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "sslmode": "disable",
        },
    )
    assert profile.status_code == 200, profile.text
    connection_id = profile.json()["id"]
    assert client.post(f"/api/v1/connections/{connection_id}/test").json() == {"ok": True}
    tables = client.get(f"/api/v1/connections/{connection_id}/tables").json()["items"]
    assert {"schema": "public", "name": "import_source"} in tables
    preview = client.post(
        f"/api/v1/connections/{connection_id}/preview",
        json={"schema": "public", "table": "import_source"},
    )
    assert preview.json() == {"columns": ["id", "label"], "rows": [[1, "Ada"], [2, "Grace"]]}

    imported = client.post(
        f"/api/v1/connections/{connection_id}/import",
        json={"schema": "public", "table": "import_source", "name": "Remote snapshot"},
    )
    assert imported.status_code == 200, imported.text
    selected = client.get(
        "/api/v1/project", headers={"X-Goldenmatch-Dataset": imported.json()["id"]}
    ).json()
    assert selected["dataset_id"] == imported.json()["id"]
    monkeypatch.setattr(connections, "MAX_ROWS", 1)

    rejected = client.post(
        f"/api/v1/connections/{connection_id}/import",
        json={"schema": "public", "table": "import_source", "name": "Too many"},
    )
    assert rejected.status_code == 413
    with psycopg.connect(postgres_url.url()) as conn:
        assert conn.execute("SELECT count(*) FROM import_source").fetchone()[0] == 2
