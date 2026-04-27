from __future__ import annotations

import json
import os
import shutil
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from dotenv import load_dotenv

from pipeline import run_pipeline


load_dotenv()


APP = FastAPI(
    title="Ecno Assist API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
TASKS_DIR = Path("tasks")
FRONTEND_FILE = Path("frontend") / "index.html"
ALLOWED_STATUSES = {"pending", "running", "succeeded", "failed"}
TASK_RETENTION_HOURS = int(os.getenv("TASK_RETENTION_HOURS", "24"))
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "")
MAX_UPLOAD_SIZE = 20 * 1024 * 1024


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def task_dir_for(task_id: str) -> Path:
    return TASKS_DIR / task_id


def status_file_for(task_id: str) -> Path:
    return task_dir_for(task_id) / "status.json"


def error_file_for(task_id: str) -> Path:
    return task_dir_for(task_id) / "error.txt"


def output_file_for(task_id: str) -> Path:
    return task_dir_for(task_id) / "output.docx"


def verify_access_password(access_password: str | None) -> None:
    if not ACCESS_PASSWORD:
        return
    if access_password != ACCESS_PASSWORD:
        raise HTTPException(status_code=401, detail="invalid access password")


def read_status(task_id: str) -> dict:
    status_file = status_file_for(task_id)
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="task not found")
    return json.loads(status_file.read_text(encoding="utf-8"))


def cleanup_expired_tasks() -> int:
    if TASK_RETENTION_HOURS <= 0:
        return 0

    if not TASKS_DIR.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=TASK_RETENTION_HOURS)
    deleted_count = 0

    for task_dir in TASKS_DIR.iterdir():
        if not task_dir.is_dir():
            continue

        status_file = task_dir / "status.json"
        if not status_file.exists():
            continue

        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        status = payload.get("status")
        if status not in {"succeeded", "failed"}:
            continue

        updated_at = parse_iso_datetime(payload.get("updated_at", ""))
        if updated_at is None or updated_at > cutoff:
            continue

        shutil.rmtree(task_dir, ignore_errors=True)
        deleted_count += 1

    return deleted_count


def write_status(task_id: str, status: str, **extra_fields: str) -> dict:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"unsupported status: {status}")

    task_dir = task_dir_for(task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    status_file = status_file_for(task_id)
    existing = {}
    if status_file.exists():
        existing = json.loads(status_file.read_text(encoding="utf-8"))

    created_at = existing.get("created_at", utc_now_iso())
    payload = {
        "task_id": task_id,
        "status": status,
        "created_at": created_at,
        "updated_at": utc_now_iso(),
    }
    payload.update(existing)
    payload.update(extra_fields)
    payload["task_id"] = task_id
    payload["status"] = status
    payload["created_at"] = created_at
    payload["updated_at"] = utc_now_iso()
    status_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def run_task(task_id: str) -> None:
    task_dir = task_dir_for(task_id)
    input_file = task_dir / "input.epub"
    error_file = error_file_for(task_id)
    output_file = output_file_for(task_id)

    if error_file.exists():
        error_file.unlink()
    if output_file.exists():
        output_file.unlink()

    write_status(task_id, "running")
    try:
        run_pipeline(input_file, task_dir=task_dir)
    except Exception:
        error_file.write_text(traceback.format_exc(), encoding="utf-8")
        write_status(task_id, "failed")
        return

    write_status(task_id, "succeeded")


@APP.get("/")
def index() -> HTMLResponse:
    if not FRONTEND_FILE.exists():
        raise HTTPException(status_code=404, detail="frontend not found")
    return HTMLResponse(FRONTEND_FILE.read_text(encoding="utf-8"))


@APP.get("/api-info")
def api_info() -> dict:
    return {
        "service": "Ecno Assist API",
        "docs_url": None,
        "health_url": "/healthz",
        "max_upload_size_mb": 20,
    }


@APP.get("/healthz")
def healthz() -> dict:
    deleted_count = cleanup_expired_tasks()
    return {
        "status": "ok",
        "tasks_dir": str(TASKS_DIR),
        "task_retention_hours": TASK_RETENTION_HOURS,
        "cleaned_tasks": deleted_count,
    }


@APP.post("/tasks")
async def create_task(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    access_password: str = Form(""),
) -> dict:
    cleanup_expired_tasks()
    verify_access_password(access_password)
    filename = file.filename or ""
    if not filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="only .epub files are supported")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="file size exceeds 20MB limit")

    task_id = uuid.uuid4().hex
    task_dir = task_dir_for(task_id)
    task_dir.mkdir(parents=True, exist_ok=False)

    input_file = task_dir / "input.epub"
    input_file.write_bytes(content)

    status = write_status(task_id, "pending", source_filename=Path(filename).name)
    background_tasks.add_task(run_task, task_id)
    return status


@APP.get("/tasks/{task_id}")
def get_task_status(task_id: str, access_password: str = Query("")) -> dict:
    verify_access_password(access_password)
    payload = read_status(task_id)
    error_file = error_file_for(task_id)
    if payload["status"] == "failed" and error_file.exists():
        payload["error"] = error_file.read_text(encoding="utf-8")[:2000]
    return payload


@APP.get("/tasks/{task_id}/download")
def download_task_output(task_id: str, access_password: str = Query("")) -> FileResponse:
    verify_access_password(access_password)
    payload = read_status(task_id)
    if payload["status"] != "succeeded":
        raise HTTPException(status_code=409, detail="task is not ready for download")

    output_file = output_file_for(task_id)
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="output file not found")

    source_filename = payload.get("source_filename", "output.epub")
    download_name = f"{Path(source_filename).stem}.docx"

    return FileResponse(
        path=output_file,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
