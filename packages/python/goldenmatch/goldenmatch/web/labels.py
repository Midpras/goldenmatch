"""Web-UI label persistence.

Full-data labels append to ``project_root/labels.jsonl`` and are deduplicated
by canonical pair on read. Preview labels live in each preview registry
entry's temporary directory, preventing sampled row IDs from colliding with
full-dataset decisions.

This JSONL shape remains separate from ``goldenmatch label`` CLI CSV output.
Labels tied to a saved full-data run are mirrored to dataset-scoped Learning
Memory by the labels router; preview decisions are never mirrored.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def _canonical_pair(row_id_a: int, row_id_b: int) -> tuple[int, int]:
    """Match the project-wide pair canonicalization (min, max).

    See the "Scored pairs are canonicalized" gotcha in the package CLAUDE.md.
    Without this, the inspector listing pair (1, 0) and the workbench
    relabeling pair (0, 1) would appear as separate entries.
    """
    a, b = int(row_id_a), int(row_id_b)
    return (a, b) if a <= b else (b, a)


def append_label(path: Path, entry: dict) -> dict:
    a, b = _canonical_pair(entry["row_id_a"], entry["row_id_b"])
    # Rebind to a fresh dict so the caller's payload isn't aliased.
    entry = {**entry, "row_id_a": a, "row_id_b": b, "ts": datetime.now(UTC).isoformat()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_labels_dedup(path: Path) -> list[dict]:
    if not path.exists():
        return []
    by_pair: dict[tuple[int, int], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # Tolerate a torn write at the tail of the file (single-writer
            # assumption holds, but a crashed-during-append leaves one bad
            # line). Skip rather than 500 the GET.
            continue
        key = _canonical_pair(rec["row_id_a"], rec["row_id_b"])
        # Keep the canonical key in the returned record too, so consumers
        # see the same shape regardless of input order.
        rec["row_id_a"], rec["row_id_b"] = key
        by_pair[key] = rec
    return list(by_pair.values())
