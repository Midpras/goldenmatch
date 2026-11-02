from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, model_validator

from goldenmatch.web.datasets import label_path_for_run, request_dataset_state
from goldenmatch.web.labels import append_label, read_labels_dedup

router = APIRouter(prefix="/api/v1/labels")
log = logging.getLogger(__name__)


class LabelIn(BaseModel):
    row_id_a: int
    row_id_b: int
    label: Literal["match", "non_match"]
    note: str | None = None
    run_name: str | None = None

    @model_validator(mode="after")
    def _reject_self_pair(self) -> LabelIn:
        if self.row_id_a == self.row_id_b:
            raise ValueError("row_id_a and row_id_b must differ (self-pair has no meaning)")
        return self


def _mirror_to_memory_store(payload: LabelIn, project_root, dataset_id: str) -> tuple[bool, str | None]:
    """Mirror a saved full-data run decision into dataset-scoped Learning Memory.

    Preview labels are stored separately and never mirrored because sampled
    row IDs do not correspond to the full dataset.
    """
    try:
        from goldenmatch._api import add_correction
        decision = "merge" if payload.label == "match" else "reject"
        add_correction(
            id_a=payload.row_id_a,
            id_b=payload.row_id_b,
            decision=decision,
            source="steward",
            reason=payload.note,
            dataset=dataset_id,
            path=str(Path(project_root) / ".goldenmatch" / "memory.db"),
        )
        return True, None
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        log.warning("label mirror to MemoryStore failed: %s", msg)
        return False, msg


@router.post("")
def post_label(payload: LabelIn, request: Request) -> dict:
    state = request_dataset_state(request)
    target = label_path_for_run(state, payload.run_name) if payload.run_name else state.labels_path
    target.parent.mkdir(parents=True, exist_ok=True)
    is_saved_run = payload.run_name is not None and target == state.labels_path
    record = append_label(target, payload.model_dump())
    mirrored, mirror_error = (
        _mirror_to_memory_store(payload, state.project_root, state.memory_dataset)
        if is_saved_run
        else (False, None)
    )
    record["mirrored"] = mirrored
    if mirror_error is not None:
        record["mirror_error"] = mirror_error
    return record


@router.get("")
def list_labels(request: Request, run_name: str | None = None) -> list[dict]:
    state = request_dataset_state(request)
    if run_name is None:
        return read_labels_dedup(state.labels_path)
    return read_labels_dedup(label_path_for_run(state, run_name))
