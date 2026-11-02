from __future__ import annotations

import json

import pytest


def test_profiles_return_only_summary_and_persist_encrypted_password(client, monkeypatch, sample_project):
    cryptography = pytest.importorskip("cryptography.fernet")
    key = cryptography.Fernet.generate_key().decode()
    monkeypatch.setenv("GOLDENMATCH_CONNECTION_KEY", key)
    body = {
        "name": "Warehouse",
        "host": "db.example.test",
        "port": 5432,
        "database": "records",
        "username": "reader",
        "password": "not-a-browser-secret",
        "sslmode": "verify-full",
    }
    created = client.post("/api/v1/connections", json=body)
    assert created.status_code == 200
    profile = created.json()
    assert profile["has_password"] is True
    assert "password" not in profile
    assert client.get("/api/v1/connections").json() == {
        "items": [profile],
        "configured": True,
    }

    stored = (sample_project / ".goldenmatch" / "connections.json").read_text("utf-8")
    assert "not-a-browser-secret" not in stored
    ciphertext = json.loads(stored)[profile["id"]]["password"]
    assert cryptography.Fernet(key.encode()).decrypt(ciphertext.encode()).decode() == "not-a-browser-secret"
    assert (sample_project / ".goldenmatch" / "connections.json").stat().st_mode & 0o777 == 0o600

    updated = client.put(
        f"/api/v1/connections/{profile['id']}",
        json={key: value for key, value in body.items() if key != "password"} | {"name": "Warehouse v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Warehouse v2"
    assert updated.json()["has_password"] is True
    assert "password" not in updated.json()
    assert client.delete(f"/api/v1/connections/{profile['id']}").json() == {"deleted": True}
    assert client.get("/api/v1/connections").json()["items"] == []


def test_private_and_socket_hosts_require_explicit_configuration(client, monkeypatch):
    cryptography = pytest.importorskip("cryptography.fernet")
    monkeypatch.setenv("GOLDENMATCH_CONNECTION_KEY", cryptography.Fernet.generate_key().decode())
    base = {"name": "Local", "port": 5432, "database": "db", "username": "reader", "password": "x"}
    socket_host = client.post("/api/v1/connections", json={**base, "host": "/var/run/postgresql"})
    assert socket_host.status_code == 422
    monkeypatch.delenv("GOLDENMATCH_WEB_ALLOWED_DB_HOSTS", raising=False)
    private_host = client.post("/api/v1/connections", json={**base, "host": "127.0.0.1"})
    assert private_host.status_code == 422


def test_missing_or_rotated_encryption_key_is_reported_without_exposing_secrets(
    client, monkeypatch
):
    cryptography = pytest.importorskip("cryptography.fernet")
    monkeypatch.delenv("GOLDENMATCH_CONNECTION_KEY", raising=False)
    assert client.get("/api/v1/connections").json()["configured"] is False
    key = cryptography.Fernet.generate_key().decode()
    monkeypatch.setenv("GOLDENMATCH_CONNECTION_KEY", key)
    body = {
        "name": "Warehouse",
        "host": "db.example.test",
        "database": "records",
        "username": "reader",
        "password": "private-value",
    }
    saved = client.post("/api/v1/connections", json=body)
    assert saved.status_code == 200

    monkeypatch.setenv(
        "GOLDENMATCH_CONNECTION_KEY", cryptography.Fernet.generate_key().decode()
    )
    assert client.get("/api/v1/connections").json()["configured"] is True
    update = client.put(
        f"/api/v1/connections/{saved.json()['id']}",
        json={key: value for key, value in body.items() if key != "password"},
    )
    assert update.status_code == 503
    assert "private-value" not in update.text
    recovered = client.put(
        f"/api/v1/connections/{saved.json()['id']}",
        json={**body, "password": "replacement-secret"},
    )
    assert recovered.status_code == 200
    assert "replacement-secret" not in recovered.text
    # A later edit without the password exercises decryption under the new key.
    subsequent = client.put(
        f"/api/v1/connections/{saved.json()['id']}",
        json={field: value for field, value in body.items() if field != "password"},
    )
    assert subsequent.status_code == 200
