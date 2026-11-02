from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from goldenmatch.web.state import AppState

router = APIRouter(prefix="/api/v1")
MAX_UPLOAD_BYTES = int(os.getenv("GOLDENMATCH_WEB_UPLOAD_MAX_BYTES", 25 * 1024 * 1024))
MAX_ROWS = int(os.getenv("GOLDENMATCH_WEB_IMPORT_MAX_ROWS", "100000"))
MAX_COLUMNS = int(os.getenv("GOLDENMATCH_WEB_IMPORT_MAX_COLUMNS", "256"))
MAX_CELL_CHARS = int(os.getenv("GOLDENMATCH_WEB_IMPORT_MAX_CELL_CHARS", "100000"))
MAX_OUTPUT_BYTES = int(os.getenv("GOLDENMATCH_WEB_IMPORT_MAX_OUTPUT_BYTES", str(100 * 1024 * 1024)))
MAX_PREVIEW_BYTES = int(os.getenv("GOLDENMATCH_WEB_PREVIEW_MAX_BYTES", str(1024 * 1024)))
MAX_XLSX_EXPANDED_BYTES = int(os.getenv("GOLDENMATCH_WEB_XLSX_MAX_EXPANDED_BYTES", str(100 * 1024 * 1024)))
MAX_XLSX_RATIO = 100
IMPORT_SLOT = threading.BoundedSemaphore(1)
PARSE_SLOT = threading.BoundedSemaphore(2)
UPLOAD_TTL_SECONDS = 3600
_UPLOAD_ID = re.compile(r"^[a-f0-9]{32}$")
_LEGACY_SUMMARY_CACHE: dict[Path, tuple[int, int, list[str], int | None]] = {}


def import_worker(handler):
    @wraps(handler)
    def guarded(*args, **kwargs):
        if not IMPORT_SLOT.acquire(blocking=False):
            raise HTTPException(429, detail="Another import is in progress; retry after it finishes")
        if not PARSE_SLOT.acquire(blocking=False):
            IMPORT_SLOT.release()
            raise HTTPException(429, detail="Dataset processing capacity is busy; retry shortly")
        try:
            return handler(*args, **kwargs)
        finally:
            PARSE_SLOT.release()
            IMPORT_SLOT.release()
    return guarded


def parse_worker(handler):
    @wraps(handler)
    def guarded(*args, **kwargs):
        if not PARSE_SLOT.acquire(blocking=False):
            raise HTTPException(429, detail="Dataset preview capacity is busy; retry shortly")
        try:
            return handler(*args, **kwargs)
        finally:
            PARSE_SLOT.release()
    return guarded


@contextmanager
def parser_slot():
    if not PARSE_SLOT.acquire(blocking=False):
        raise HTTPException(429, detail="Dataset processing capacity is busy; retry shortly")
    try:
        yield
    finally:
        PARSE_SLOT.release()


def workspace(request: Request) -> Path:
    return Path(request.app.state.app_state.project_root).resolve()


def dataset_root(root: Path, dataset_id: str) -> Path:
    if dataset_id == "legacy":
        if not (root / "data.csv").is_file():
            raise HTTPException(404, detail="legacy dataset is not available")
        return root
    if not re.fullmatch(r"[a-f0-9]{32}", dataset_id):
        raise HTTPException(404, detail="dataset not found")
    path = root / ".goldenmatch" / "datasets" / dataset_id
    if not (path / "data.csv").is_file():
        raise HTTPException(404, detail="dataset not found")
    return path


def selected_dataset_id(request: Request) -> str:
    root = workspace(request)
    dataset_id = request.headers.get("X-Goldenmatch-Dataset")
    if dataset_id:
        dataset_root(root, dataset_id)
        return dataset_id
    if (root / "data.csv").is_file():
        return "legacy"
    raise HTTPException(409, detail="No dataset selected; import a dataset first")


def request_dataset_state(request: Request, dataset_id: str | None = None) -> AppState:
    """Resolve request-local state while preserving the existing legacy state."""
    base = request.app.state.app_state
    selected = dataset_id or selected_dataset_id(request)
    if selected == "legacy":
        return base
    with base.dataset_states_lock:
        if selected not in base.dataset_states:
            root = dataset_root(Path(base.project_root).resolve(), selected)
            cfg = root / "goldenmatch.yml"
            base.dataset_states[selected] = AppState(
                project_root=root,
                config_path=cfg if cfg.exists() else None,
                labels_path=root / "labels.jsonl",
                runs_dir=root,
                dataset_id=selected,
            )
        return base.dataset_states[selected]



def label_path_for_run(state: AppState, run_name: str) -> Path:
    preview_labels = state.registry.labels_path(run_name)
    if preview_labels is not None:
        return preview_labels
    from goldenmatch.web.runs import discover_runs

    if any(ref.run_name == run_name for ref in discover_runs(state.runs_dir or state.project_root)):
        return state.labels_path
    raise HTTPException(404, detail="run not found for selected dataset")

def _summary(root: Path, dataset_id: str, name: str, source: str, created_at: str | None = None) -> dict[str, Any]:
    directory = dataset_root(root, dataset_id)
    meta = _read_meta(directory)
    if dataset_id != "legacy" and "row_count" in meta and "columns" in meta:
        columns, count = meta["columns"], meta["row_count"]
    else:
        data_path = directory / "data.csv"
        try:
            stat = data_path.stat()
            cached = _LEGACY_SUMMARY_CACHE.get(data_path)
            if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
                columns, count = cached[2], cached[3]
            else:
                with data_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    reader = csv.reader(stream, strict=True)
                    columns = next(reader)
                    count = sum(1 for _ in reader)
                _LEGACY_SUMMARY_CACHE[data_path] = (stat.st_mtime_ns, stat.st_size, columns, count)
        except Exception:
            columns, count = [], None
    return {"id": dataset_id, "name": name, "source": source, "row_count": count,
            "columns": columns, "created_at": created_at or meta.get("created_at")}


def _read_meta(path: Path) -> dict[str, Any]:
    try:
        value = json.loads((path / "manifest.json").read_text("utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _staging(root: Path) -> Path:
    path = root / ".goldenmatch" / "staging"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(UTC).timestamp()
    for child in path.iterdir():
        try:
            if now - child.stat().st_mtime > UPLOAD_TTL_SECONDS:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            pass
    return path


@router.get("/datasets")
def list_datasets(request: Request) -> dict[str, Any]:
    root = workspace(request)
    items = []
    if (root / "data.csv").is_file():
        items.append(_summary(root, "legacy", root.name, "legacy"))
    base = root / ".goldenmatch" / "datasets"
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if not re.fullmatch(r"[a-f0-9]{32}", path.name) or not (path / "data.csv").is_file():
                continue
            meta = _read_meta(path)
            items.append(_summary(root, path.name, str(meta.get("name", path.name)),
                                  str(meta.get("source", "upload")), meta.get("created_at")))
    return {"items": items}


@router.post("/datasets/uploads")
async def upload_dataset(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    name = file.filename or ""
    if Path(name).name != name or name in {".", ".."} or "\\" in name:
        raise HTTPException(400, detail="invalid upload filename")
    suffix = Path(name).suffix.lower()
    if suffix == ".xls":
        raise HTTPException(415, detail="Legacy .xls files are not supported; upload .xlsx or .csv")
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(415, detail="Only CSV and .xlsx files are supported")
    target_dir = _staging(workspace(request)) / uuid.uuid4().hex
    target_dir.mkdir(mode=0o700)
    path = target_dir / ("upload.csv" if suffix == ".csv" else "upload.xlsx")
    size = 0
    try:
        with path.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, detail=f"Upload exceeds {MAX_UPLOAD_BYTES} byte limit")
                out.write(chunk)
        if suffix == ".xlsx":
            with parser_slot():
                with zipfile.ZipFile(path) as zf:
                    infos = zf.infolist()
                    expanded = sum(info.file_size for info in infos)
                    if expanded > MAX_XLSX_EXPANDED_BYTES or any(
                        info.file_size > 0 and info.file_size / max(info.compress_size, 1) > MAX_XLSX_RATIO
                        for info in infos
                    ):
                        raise HTTPException(413, detail="Workbook expanded size exceeds the allowed limit")
                    if "xl/workbook.xml" not in zf.namelist():
                        raise HTTPException(400, detail="Invalid .xlsx workbook")
                import openpyxl
                book = openpyxl.load_workbook(path, read_only=True, data_only=False)
                try:
                    sheets = list(book.sheetnames)
                finally:
                    book.close()
        else:
            sheets = []
        (target_dir / "source.json").write_text(json.dumps({"filename": name, "suffix": suffix}), "utf-8")
        return {"upload_id": target_dir.name, "sheets": sheets}
    except HTTPException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(400, detail=f"Invalid upload: {type(exc).__name__}") from exc
    finally:
        await file.close()


def _upload_path(root: Path, upload_id: str) -> tuple[Path, str]:
    if not _UPLOAD_ID.fullmatch(upload_id):
        raise HTTPException(404, detail="Upload not found or expired")
    directory = root / ".goldenmatch" / "staging" / upload_id
    if not directory.is_dir():
        raise HTTPException(404, detail="Upload not found or expired")
    if datetime.now(UTC).timestamp() - directory.stat().st_mtime > UPLOAD_TTL_SECONDS:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(404, detail="Upload not found or expired")
    source = json.loads((directory / "source.json").read_text("utf-8"))
    return directory, source["suffix"]


def _validate_columns(columns: list[str]) -> list[str]:
    columns = [value.strip() for value in columns]
    if not columns or len(columns) > MAX_COLUMNS or any(not value or len(value) > MAX_CELL_CHARS for value in columns):
        raise ValueError(f"Header must have 1-{MAX_COLUMNS} non-empty columns")
    if len(set(columns)) != len(columns) or any(value.startswith("__") for value in columns):
        raise ValueError("Column names must be unique and cannot begin with '__'")
    return columns


def _validate_row(row: list[Any], columns: list[str]) -> list[Any]:
    if len(row) != len(columns):
        raise ValueError("Rows must have the same number of values as the header")
    normalized = []
    for value in row:
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
            raise ValueError(f"Cell exceeds {MAX_CELL_CHARS} character limit")
        normalized.append(value)
    return normalized


@contextmanager
def _table(path: Path, suffix: str, sheet: str | None, delimiter: str | None):
    """Yield validated header and bounded-memory row iterator; resources close on every exit."""
    if delimiter is not None and len(delimiter) != 1:
        raise ValueError("Delimiter must be one character")
    if suffix == ".xlsx":
        import openpyxl
        formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
        try:
            values_book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception:
            formulas.close()
            raise
        try:
            worksheet = formulas[sheet]
            value_sheet = values_book[sheet]
            if (worksheet.max_column or 0) > MAX_COLUMNS or (worksheet.max_row or 0) > MAX_ROWS + 1:
                raise ValueError("Worksheet dimensions exceed the configured row or column limit")
            formula_rows = worksheet.iter_rows()
            value_rows = value_sheet.iter_rows(values_only=True)
            try:
                formula_header, value_header = next(formula_rows), next(value_rows)
            except StopIteration as exc:
                raise ValueError("Worksheet is empty") from exc
            if len(value_header) > MAX_COLUMNS:
                raise ValueError(f"Workbook exceeds {MAX_COLUMNS} column limit")
            if any(cell.data_type == "f" and value is None for cell, value in zip(formula_header, value_header)):
                raise ValueError("Workbook contains formulas without cached values; recalculate and save it before importing")
            columns = _validate_columns([str(value) if value is not None else "" for value in value_header])

            def rows() -> Iterator[list[Any]]:
                count = 0
                for formula_row, row in zip(formula_rows, value_rows, strict=False):
                    if count >= MAX_ROWS:
                        raise ValueError(f"Import exceeds {MAX_ROWS} row limit")
                    if len(row) > MAX_COLUMNS:
                        raise ValueError(f"Workbook exceeds {MAX_COLUMNS} column limit")
                    if any(cell.data_type == "f" and value is None for cell, value in zip(formula_row, row)):
                        raise ValueError("Workbook contains formulas without cached values; recalculate and save it before importing")
                    count += 1
                    yield _validate_row(list(row), columns)
            yield columns, rows()
        finally:
            formulas.close()
            values_book.close()
    else:
        stream = path.open("r", encoding="utf-8-sig", newline="")
        try:
            reader = csv.reader(stream, delimiter=delimiter or ",", strict=True)
            try:
                columns = _validate_columns(next(reader))
            except StopIteration as exc:
                raise ValueError("CSV is empty") from exc

            def rows() -> Iterator[list[Any]]:
                count = 0
                for row in reader:
                    if count >= MAX_ROWS:
                        raise ValueError(f"Import exceeds {MAX_ROWS} row limit")
                    count += 1
                    yield _validate_row(row, columns)
            yield columns, rows()
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must be UTF-8 encoded") from exc
        finally:
            stream.close()


def _publish(root: Path, name: str, source: str, columns: list[str], rows: Iterator[list[Any]]) -> dict[str, Any]:
    datasets = root / ".goldenmatch" / "datasets"
    datasets.mkdir(parents=True, exist_ok=True)
    dataset_id = uuid.uuid4().hex
    stage = Path(tempfile.mkdtemp(prefix=".publish-", dir=datasets))
    count = 0
    try:
        data_path = stage / "data.csv"
        with data_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(columns)
            if output.tell() > MAX_OUTPUT_BYTES:
                raise ValueError(f"Normalized dataset exceeds {MAX_OUTPUT_BYTES} byte limit")
            for row in rows:
                writer.writerow(row)
                count += 1
                if output.tell() > MAX_OUTPUT_BYTES:
                    raise ValueError(f"Normalized dataset exceeds {MAX_OUTPUT_BYTES} byte limit")
            output.flush()
            os.fsync(output.fileno())
        created = datetime.now(UTC).isoformat()
        manifest = {"id": dataset_id, "name": name, "source": source, "created_at": created,
                    "row_count": count, "columns": columns}
        with (stage / "manifest.json").open("w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, datasets / dataset_id)
        return {"id": dataset_id, "name": name, "source": source, "row_count": count,
                "columns": columns, "created_at": created}
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _append_preview_row(rows: list[list[Any]], row: list[Any], base_bytes: int = 0) -> None:
    candidate_bytes = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    used_bytes = base_bytes + sum(
        len(json.dumps(existing, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for existing in rows
    )
    if candidate_bytes + used_bytes > MAX_PREVIEW_BYTES:
        raise HTTPException(413, detail=f"Preview exceeds {MAX_PREVIEW_BYTES} byte limit")
    rows.append(row)


def _validate_preview_columns(columns: list[str]) -> int:
    size = len(json.dumps(columns, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_PREVIEW_BYTES:
        raise HTTPException(413, detail=f"Preview exceeds {MAX_PREVIEW_BYTES} byte limit")
    return size


class UploadPreview(BaseModel):
    sheet: str | None = None
    delimiter: str | None = None


@router.post("/datasets/uploads/{upload_id}/preview")
@parse_worker
def preview_upload(upload_id: str, body: UploadPreview, request: Request) -> dict[str, Any]:
    directory, suffix = _upload_path(workspace(request), upload_id)
    try:
        with _table(directory / ("upload.csv" if suffix == ".csv" else "upload.xlsx"), suffix, body.sheet, body.delimiter) as (columns, rows):
            preview_bytes = _validate_preview_columns(columns)
            preview = []
            for row in rows:
                if len(preview) < 20:
                    _append_preview_row(preview, row, preview_bytes)
                    if len(preview) == 20:
                        break
        return {"columns": columns, "rows": preview}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, detail=str(exc)) from exc


class ImportUpload(UploadPreview):
    name: str = Field(min_length=1, max_length=128)


@router.post("/datasets/uploads/{upload_id}/import")
@import_worker
def import_upload(upload_id: str, body: ImportUpload, request: Request) -> dict[str, Any]:
    root = workspace(request)
    directory, suffix = _upload_path(root, upload_id)
    try:
        with _table(directory / ("upload.csv" if suffix == ".csv" else "upload.xlsx"), suffix, body.sheet, body.delimiter) as (columns, rows):
            result = _publish(root, body.name, "upload", columns, rows)
        shutil.rmtree(directory, ignore_errors=True)
        return result
    except HTTPException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(400, detail=str(exc)) from exc
