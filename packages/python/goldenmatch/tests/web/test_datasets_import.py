from __future__ import annotations

from io import BytesIO

import pytest


def _upload(client, filename: str, content: bytes) -> str:
    response = client.post(
        "/api/v1/datasets/uploads",
        files={"file": (filename, content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()["upload_id"]


def test_csv_import_publishes_isolated_snapshot_and_rejects_invalid_followup(client):
    first_id = _upload(client, "first.csv", b"email,name\na@example.test,Ada\n")
    preview = client.post(
        f"/api/v1/datasets/uploads/{first_id}/preview", json={"delimiter": ","}
    )
    assert preview.json() == {
        "columns": ["email", "name"],
        "rows": [["a@example.test", "Ada"]],
    }
    imported = client.post(
        f"/api/v1/datasets/uploads/{first_id}/import",
        json={"name": "First snapshot", "delimiter": ","},
    )
    assert imported.status_code == 200
    first = imported.json()
    assert first["source"] == "upload"
    assert first["row_count"] == 1
    assert client.get("/api/v1/project", headers={"X-Goldenmatch-Dataset": first["id"]}).json()["dataset_id"] == first["id"]

    broken_id = _upload(client, "broken.csv", b"email,email\nx,y\n")
    rejected = client.post(
        f"/api/v1/datasets/uploads/{broken_id}/import", json={"name": "Bad"}
    )
    assert rejected.status_code == 400
    listings = client.get("/api/v1/datasets").json()["items"]
    assert [item["id"] for item in listings].count(first["id"]) == 1
    assert not any(item["name"] == "Bad" for item in listings)


def test_xlsx_import_uses_the_selected_sheet(client):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    first = book.active
    first.title = "Ignore"
    first.append(["name", "city"])
    first.append(["Grace", "London"])
    selected = book.create_sheet("Selected")
    selected.append(["name", "city"])
    selected.append(["Ada", "London"])
    content = BytesIO()
    book.save(content)

    upload = client.post(
        "/api/v1/datasets/uploads",
        files={"file": ("people.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert upload.status_code == 200, upload.text
    upload_id = upload.json()["upload_id"]
    assert upload.json()["sheets"] == ["Ignore", "Selected"]
    preview = client.post(
        f"/api/v1/datasets/uploads/{upload_id}/preview", json={"sheet": "Selected"}
    )
    assert preview.json() == {"columns": ["name", "city"], "rows": [["Ada", "London"]]}
    imported = client.post(
        f"/api/v1/datasets/uploads/{upload_id}/import",
        json={"name": "People", "sheet": "Selected"},
    )
    assert imported.status_code == 200
    assert imported.json()["row_count"] == 1


def test_legacy_xls_is_rejected_without_publishing(client):
    response = client.post(
        "/api/v1/datasets/uploads",
        files={"file": ("old.xls", b"not a workbook", "application/vnd.ms-excel")},
    )
    assert response.status_code == 415
    assert "not supported" in response.json()["detail"]
    assert all(item["source"] != "upload" for item in client.get("/api/v1/datasets").json()["items"])


def test_normalized_output_cap_rejects_import_without_publishing(client, monkeypatch):
    from goldenmatch.web import datasets

    upload_id = _upload(client, "large-normalized.csv", b"name\n" + b"x" * 200 + b"\n")
    monkeypatch.setattr(datasets, "MAX_OUTPUT_BYTES", 64)
    response = client.post(
        f"/api/v1/datasets/uploads/{upload_id}/import",
        json={"name": "Too large"},
    )
    assert response.status_code == 400
    assert not any(item["name"] == "Too large" for item in client.get("/api/v1/datasets").json()["items"])


def test_multipart_request_body_is_capped_before_upload_parsing(
    client, monkeypatch, sample_project
):
    from goldenmatch.web import datasets

    monkeypatch.setattr(datasets, "MAX_UPLOAD_BYTES", 32)
    response = client.post(
        "/api/v1/datasets/uploads",
        files={"file": ("large.csv", b"x" * (1024 * 1024 + 64), "text/csv")},
    )
    assert response.status_code == 413
    staging = sample_project / ".goldenmatch" / "staging"
    assert not staging.exists() or not list(staging.iterdir())
