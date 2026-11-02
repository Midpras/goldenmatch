from __future__ import annotations


def _import_csv(client, name: str, value: str) -> str:
    upload = client.post(
        "/api/v1/datasets/uploads",
        files={"file": (f"{name}.csv", f"name\n{value}\n".encode(), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    result = client.post(
        f"/api/v1/datasets/uploads/{upload.json()['upload_id']}/import",
        json={"name": name},
    )
    assert result.status_code == 200, result.text
    return result.json()["id"]


def test_match_uses_selected_snapshot_and_second_imported_reference(client):
    target_id = _import_csv(client, "Target", "Ada Lovelace")
    reference_id = _import_csv(client, "Reference", "Ada Lovelace")
    response = client.post(
        "/api/v1/match",
        headers={"X-Goldenmatch-Dataset": target_id},
        json={
            "reference_dataset_id": reference_id,
            "rules": {
                "threshold": 0.7,
                "matchkeys": [
                    {"column": "name", "scorer": "jaro_winkler", "weight": 1.0, "transforms": []}
                ],
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["stats"]["target_total"] == 1
    assert response.json()["stats"]["reference_total"] == 1
    assert response.json()["stats"]["matched_pairs"] == 1
