from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from goldenmatch.web.datasets import (
    MAX_CELL_CHARS,
    MAX_ROWS,
    _append_preview_row,
    _publish,
    _validate_columns,
    _validate_preview_columns,
    import_worker,
    parse_worker,
    workspace,
)

router = APIRouter(prefix="/api/v1/connections")
_ID = re.compile(r"^[a-f0-9]{32}$")

_PROFILE_LOCK = threading.RLock()

def _key():
    value = os.getenv("GOLDENMATCH_CONNECTION_KEY")
    if not value:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(value.encode())
    except Exception as exc:
        raise HTTPException(503, detail="GOLDENMATCH_CONNECTION_KEY is invalid; configure a Fernet key") from exc


def _path(request: Request) -> Path:
    return workspace(request) / ".goldenmatch" / "connections.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise HTTPException(500, detail="Stored connection profiles are unreadable") from exc


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".connections-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def _summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {key: profile[key] for key in ("id", "name", "host", "port", "database", "username", "sslmode")} | {"has_password": bool(profile.get("password"))}


@router.get("")
def list_connections(request: Request) -> dict[str, Any]:
    path = _path(request)
    try:
        configured = _key() is not None
    except HTTPException:
        configured = False
    with _PROFILE_LOCK:
        rows = _load(path)
    # A valid new key must permit editing/re-entering passwords even when
    # profiles encrypted with a lost old key can no longer be decrypted.
    return {"items": [_summary(row) for row in rows.values()], "configured": configured}

class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=4096)
    sslmode: str = "verify-full"

    def valid_ssl(self):
        if self.sslmode not in {"require", "verify-full", "disable"}:
            raise HTTPException(422, detail="sslmode must be require, verify-full, or disable")


def _validate_host(host: str) -> None:
    if any(x in host for x in ("/", "\\", "@", "://")) or " " in host or host.startswith(".") or ".." in host:
        raise HTTPException(422, detail="host must be a hostname or IP address, not a DSN or socket path")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            raise HTTPException(422, detail="host must be a valid hostname or IP address")
        return
    _validate_address(address, host)


def _validate_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> None:
    allowed = {value.strip().lower().strip("[]") for value in os.getenv("GOLDENMATCH_WEB_ALLOWED_DB_HOSTS", "").split(",") if value.strip()}
    if host.lower().strip("[]") in allowed or str(address).lower() in allowed:
        return
    allow_private = os.getenv("GOLDENMATCH_WEB_ALLOW_PRIVATE_DB_HOSTS", "").lower() in {"1", "true", "yes"}
    if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
        raise HTTPException(422, detail="loopback and link-local database hosts are blocked unless explicitly allowlisted")
    if address.is_private and not allow_private:
        raise HTTPException(422, detail="private database hosts require GOLDENMATCH_WEB_ALLOW_PRIVATE_DB_HOSTS=true")

def _profile(body: ConnectionInput, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    body.valid_ssl()
    _validate_host(body.host)
    token = _key()
    if token is None:
        raise HTTPException(503, detail="Set GOLDENMATCH_CONNECTION_KEY to enable saved database connections")
    try:
        secret = body.password if body.password is not None else (
            token.decrypt(previous["password"].encode()).decode()
            if previous and previous.get("password")
            else None
        )
    except Exception as exc:
        raise HTTPException(503, detail="Stored password cannot be decrypted; restore the original GOLDENMATCH_CONNECTION_KEY or replace the password") from exc
    if not secret:
        raise HTTPException(422, detail="password is required for a new connection")
    return {"id": previous["id"] if previous else uuid.uuid4().hex, "name": body.name, "host": body.host,
            "port": body.port, "database": body.database, "username": body.username, "sslmode": body.sslmode,
            "password": token.encrypt(secret.encode()).decode()}


def _id_profiles(request: Request, connection_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not _ID.fullmatch(connection_id):
        raise HTTPException(404, detail="Connection not found")
    path = _path(request)
    rows = _load(path)
    row = rows.get(connection_id)
    if not row:
        raise HTTPException(404, detail="Connection not found")
    return path, rows, row


@router.post("")
def create_connection(body: ConnectionInput, request: Request) -> dict[str, Any]:
    profile = _profile(body)
    path = _path(request)
    with _PROFILE_LOCK:
        rows = _load(path)
        rows[profile["id"]] = profile
        _save(path, rows)
    return _summary(profile)


@router.put("/{connection_id}")
def update_connection(connection_id: str, body: ConnectionInput, request: Request) -> dict[str, Any]:
    if not _ID.fullmatch(connection_id):
        raise HTTPException(404, detail="Connection not found")
    path = _path(request)
    with _PROFILE_LOCK:
        rows = _load(path)
        old = rows.get(connection_id)
        if old is None:
            raise HTTPException(404, detail="Connection not found")
        profile = _profile(body, old)
        rows[connection_id] = profile
        _save(path, rows)
    return _summary(profile)


@router.delete("/{connection_id}")
def delete_connection(connection_id: str, request: Request) -> dict[str, bool]:
    if not _ID.fullmatch(connection_id):
        raise HTTPException(404, detail="Connection not found")
    path = _path(request)
    with _PROFILE_LOCK:
        rows = _load(path)
        if connection_id not in rows:
            raise HTTPException(404, detail="Connection not found")
        del rows[connection_id]
        _save(path, rows)
    return {"deleted": True}


def _connect(profile: dict[str, Any]):
    try:
        from cryptography.fernet import Fernet
        from psycopg import connect
        host = profile["host"]
        try:
            addresses = {ipaddress.ip_address(host.strip("[]"))}
        except ValueError:
            addresses = {ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, profile["port"], type=socket.SOCK_STREAM)}
        if not addresses:
            raise HTTPException(400, detail="Database host did not resolve")
        for address in addresses:
            _validate_address(address, host)
        secret = Fernet(os.environ["GOLDENMATCH_CONNECTION_KEY"].encode()).decrypt(profile["password"].encode()).decode()
        conn = connect(host=host, hostaddr=str(next(iter(addresses))), port=profile["port"], dbname=profile["database"], user=profile["username"],
                       password=secret, sslmode=profile["sslmode"], connect_timeout=5,
                       options="-c statement_timeout=10000 -c default_transaction_read_only=on")
        conn.execute("SET default_transaction_read_only = on")
        return conn
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, detail="Could not connect to database; check host, credentials, network access, and TLS settings") from exc


@router.post("/{connection_id}/test")
def test_connection(connection_id: str, request: Request) -> dict[str, bool]:
    _, _, profile = _id_profiles(request, connection_id)
    try:
        with _connect(profile) as conn:
            conn.execute("SELECT 1").fetchone()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, detail="Database test query failed; check connection access and network settings") from exc
    return {"ok": True}


@router.get("/{connection_id}/tables")
def list_tables(connection_id: str, request: Request) -> dict[str, Any]:
    _, _, profile = _id_profiles(request, connection_id)
    try:
        with _connect(profile) as conn:
            rows = conn.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_schema, table_name LIMIT 501").fetchall()
        if len(rows) > 500:
            rows = rows[:500]
        return {"items": [{"schema": schema, "name": name} for schema, name in rows]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, detail="Could not list database tables; check connection access and network settings") from exc


class TableRequest(BaseModel):
    schema: str = Field(min_length=1, max_length=128)
    table: str = Field(min_length=1, max_length=128)


class TableImport(TableRequest):
    name: str = Field(min_length=1, max_length=128)


def _csv_value(value: Any) -> Any:
    rendered = value if value is None or isinstance(value, (str, int, float, bool)) else str(value)
    if isinstance(rendered, str) and len(rendered) > MAX_CELL_CHARS:
        raise HTTPException(413, detail=f"Database cell exceeds {MAX_CELL_CHARS} character limit")
    return rendered


@contextmanager
def _table_data(profile: dict[str, Any], schema: str, table: str, *, preview: bool = False):
    from psycopg import sql

    try:
        with _connect(profile) as conn:
            with conn.cursor(name="goldenmatch_import") as cursor:
                cap = 21 if preview else MAX_ROWS + 1
                cursor.execute(
                    sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(sql.Identifier(schema), sql.Identifier(table)),
                    (cap,),
                )
                try:
                    columns = _validate_columns([description.name for description in cursor.description])
                except ValueError as exc:
                    raise HTTPException(400, detail="Table has invalid or unsupported column names") from exc

                def rows():
                    count = 0
                    while batch := cursor.fetchmany(2):
                        for row in batch:
                            if not preview and count >= MAX_ROWS:
                                raise HTTPException(413, detail=f"Table exceeds {MAX_ROWS} row import limit")
                            count += 1
                            yield [_csv_value(value) for value in row]

                yield columns, rows()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, detail="Could not read the selected table; verify it exists and the account has read-only access") from exc


def _preview(columns: list[str], rows) -> dict[str, Any]:
    preview_bytes = _validate_preview_columns(columns)
    preview = []
    for _, row in zip(range(20), rows):
        _append_preview_row(preview, row, preview_bytes)
    return {"columns": columns, "rows": preview}


@router.post("/{connection_id}/preview")
@parse_worker
def preview_table(connection_id: str, body: TableRequest, request: Request) -> dict[str, Any]:
    _, _, profile = _id_profiles(request, connection_id)
    with _table_data(profile, body.schema, body.table, preview=True) as (columns, rows):
        return _preview(columns, rows)


@router.post("/{connection_id}/import")
@import_worker
def import_table(connection_id: str, body: TableImport, request: Request) -> dict[str, Any]:
    root = workspace(request)
    _, _, profile = _id_profiles(request, connection_id)
    with _table_data(profile, body.schema, body.table) as (columns, rows):
        return _publish(root, body.name, "postgres", columns, rows)
