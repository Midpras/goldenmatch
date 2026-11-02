from __future__ import annotations

import pytest

from .test_dataset_matching import _import_csv


def test_overlapping_row_ids_keep_labels_and_learning_memory_dataset_local(client):
    dataset_a = _import_csv(client, "Dataset A", "Same person")
    dataset_b = _import_csv(client, "Dataset B", "Same person")
    headers_a = {"X-Goldenmatch-Dataset": dataset_a}
    headers_b = {"X-Goldenmatch-Dataset": dataset_b}

    for headers, label in ((headers_a, "match"), (headers_b, "non_match")):
        response = client.post(
            "/api/v1/labels",
            headers=headers,
            json={"row_id_a": 0, "row_id_b": 1, "label": label},
        )
        assert response.status_code == 200
        correction = client.post(
            "/api/v1/memory/corrections",
            headers=headers,
            json={"decision": "reject", "dataset": "caller-controlled", "id_a": 0, "id_b": 1},
        )
        assert correction.status_code == 201

    labels_a = client.get("/api/v1/labels", headers=headers_a).json()
    labels_b = client.get("/api/v1/labels", headers=headers_b).json()
    assert [row["label"] for row in labels_a] == ["match"]
    assert [row["label"] for row in labels_b] == ["non_match"]

    memory_a = client.get("/api/v1/memory/corrections", headers=headers_a).json()
    memory_b = client.get("/api/v1/memory/corrections", headers=headers_b).json()
    assert memory_a["total"] == memory_b["total"] == 1
    assert {row["dataset"] for row in memory_a["items"]} == {dataset_a}
    assert {row["dataset"] for row in memory_b["items"]} == {dataset_b}


def _preview(client):
    response = client.post(
        "/api/v1/preview",
        json={
            "rules": {
                "threshold": 0.5,
                "matchkeys": [{
                    "column": "name",
                    "scorer": "jaro_winkler",
                    "weight": 1.0,
                    "transforms": ["lowercase"],
                }],
            },
            "sample": {"n": 10, "seed": 42},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["run_name"]


def test_preview_labels_are_isolated_from_full_runs_and_other_previews(client):
    first_preview = _preview(client)
    first_decision = client.post(
        "/api/v1/labels",
        json={"row_id_a": 0, "row_id_b": 1, "label": "non_match", "run_name": first_preview},
    )
    assert first_decision.status_code == 200
    assert first_decision.json()["mirrored"] is False

    full_review = client.get("/api/v1/runs/20260101_000000/review").json()
    assert any({pair["row_id_a"], pair["row_id_b"]} == {0, 1} for pair in full_review)
    assert client.get("/api/v1/labels").json() == []

    second_preview = _preview(client)
    second_decision = client.post(
        "/api/v1/labels",
        json={"row_id_a": 0, "row_id_b": 1, "label": "match", "run_name": second_preview},
    )
    assert second_decision.status_code == 200
    assert [row["label"] for row in client.get(
        "/api/v1/labels", params={"run_name": first_preview}
    ).json()] == ["non_match"]
    assert [row["label"] for row in client.get(
        "/api/v1/labels", params={"run_name": second_preview}
    ).json()] == ["match"]


@pytest.mark.parametrize(("method", "path", "payload"), [
    ("POST", "/api/v1/run", {}),
    ("POST", "/api/v1/autoconfig", {}),
    ("POST", "/api/v1/preview", {
        "rules": {"threshold": 0.8, "matchkeys": [
            {"column": "name", "scorer": "exact", "weight": 1.0, "transforms": []},
        ]},
        "sample": {"n": 10},
    }),
    ("GET", "/api/v1/quality", None),
    ("GET", "/api/v1/suggest", None),
])
def test_missing_selection_never_implicitly_activates_an_import(
    client, sample_project, method, path, payload,
):
    (sample_project / "data.csv").unlink()
    dataset_id = _import_csv(client, "Unselected snapshot", "Ada")
    response = client.request(method, path, json=payload)
    assert response.status_code == 409
    selected = client.get(
        "/api/v1/project", headers={"X-Goldenmatch-Dataset": dataset_id},
    )
    assert selected.status_code == 200
    assert selected.json()["dataset_id"] == dataset_id


def test_imported_snapshot_makes_empty_workspace_ready(client, sample_project):
    (sample_project / "data.csv").unlink()
    assert client.get("/api/v1/healthz").status_code == 503
    _import_csv(client, "First snapshot", "Ada")
    readiness = client.get("/api/v1/healthz")
    assert readiness.status_code == 200
    assert readiness.json()["checks"]["data_csv"] is False
    assert readiness.json()["checks"]["imported_dataset"] is True


def test_legacy_learning_memory_remains_visible_without_leaking_into_imports(
    client, sample_project,
):
    from goldenmatch._api import add_correction

    add_correction(
        id_a=0, id_b=1, decision="reject", source="steward",
        dataset=str(sample_project),
        path=str(sample_project / ".goldenmatch" / "memory.db"),
    )
    legacy = client.get("/api/v1/memory/corrections").json()["items"]
    assert [(item["id_a"], item["id_b"], item["decision"]) for item in legacy] == [
        (0, 1, "reject"),
    ]
    snapshot_id = _import_csv(client, "New records", "Ada")
    imported = client.get(
        "/api/v1/memory/corrections",
        headers={"X-Goldenmatch-Dataset": snapshot_id},
    )
    assert imported.json()["items"] == []
