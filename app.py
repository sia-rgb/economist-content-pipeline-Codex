from __future__ import annotations

import json
import os
import re
import shutil
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
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


def parse_content_disposition(value: str) -> dict:
    params = {}
    for match in re.finditer(r';\s*([^=]+)="?([^";]*)"?', value):
        params[match.group(1).strip().lower()] = match.group(2)
    return params


def parse_multipart_request(body: bytes, content_type: str) -> tuple[dict[str, str], dict]:
    boundary_match = re.search(r"boundary=([^;]+)", content_type)
    if boundary_match is None:
        raise HTTPException(status_code=400, detail="missing multipart boundary")

    boundary = boundary_match.group(1).strip().strip('"').encode("utf-8")
    boundary_marker = b"--" + boundary
    fields = {}
    files = {}

    for raw_part in body.split(boundary_marker):
        part = raw_part
        if not part or part in {b"--", b"--\r\n"}:
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"--\r\n"):
            part = part[:-4]
        elif part.endswith(b"--"):
            part = part[:-2]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part:
            continue

        header_blob, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            continue

        headers = {}
        for header_line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
            if ":" not in header_line:
                continue
            key, value = header_line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        disposition = headers.get("content-disposition", "")
        disposition_params = parse_content_disposition(disposition)
        field_name = disposition_params.get("name")
        if not field_name:
            continue

        filename = disposition_params.get("filename")
        if filename is None:
            fields[field_name] = content.decode("utf-8", errors="replace")
            continue

        files[field_name] = {
            "filename": filename,
            "content_type": headers.get("content-type", ""),
            "content": content,
        }

    return fields, files


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


def render_task_page(task_id: str) -> str:
    task_id_json = json.dumps(task_id)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>任务处理中</title>
  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Georgia, "Times New Roman", serif;
      color: #2b2418;
      background: #f6f0e6;
    }}

    main {{
      width: min(560px, calc(100% - 32px));
      margin: 0 auto;
      padding: 72px 0;
    }}

    section {{
      padding: 28px;
      border: 1px solid #d8c7aa;
      border-radius: 8px;
      background: #fffaf2;
      box-shadow: 0 18px 50px rgba(80, 58, 33, 0.1);
    }}

    h1 {{
      margin: 0 0 16px;
      font-size: 32px;
      line-height: 1.15;
      text-align: center;
    }}

    p {{
      color: #6f6556;
      font-size: 14px;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }}

    .actions {{
      display: flex;
      gap: 10px;
      margin-top: 18px;
      flex-wrap: wrap;
    }}

    a {{
      min-height: 42px;
      padding: 10px 16px;
      border-radius: 6px;
      color: #fff;
      text-decoration: none;
      background: #9f4a22;
    }}

    #downloadLink {{
      background: #236b45;
    }}

    #downloadLink[aria-disabled="true"] {{
      background: #d9d1c4;
      color: #6f6556;
      pointer-events: none;
    }}

    .message {{
      color: #236b45;
    }}

    .error {{
      color: #a12727;
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>任务处理中</h1>
      <p>任务 ID：<span id="taskId"></span></p>
      <p id="messageText" class="message">任务已提交，正在处理。</p>
      <p id="errorText" class="error"></p>
      <div class="actions">
        <a href="/">继续上传</a>
        <a id="downloadLink" href="#" aria-disabled="true">下载 Word</a>
      </div>
    </section>
  </main>
  <script>
    const taskId = {task_id_json};
    const taskIdText = document.getElementById("taskId");
    const messageText = document.getElementById("messageText");
    const errorText = document.getElementById("errorText");
    const downloadLink = document.getElementById("downloadLink");

    taskIdText.textContent = taskId;

    function showDownload() {{
      downloadLink.href = `/tasks/${{taskId}}/download?access_password=`;
      downloadLink.setAttribute("aria-disabled", "false");
    }}

    async function pollStatus() {{
      try {{
        const response = await fetch(`/tasks/${{taskId}}?access_password=`);
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {{
          messageText.textContent = "连接波动，正在重试。";
          setTimeout(pollStatus, 3000);
          return;
        }}

        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(payload.detail || "查询状态失败");
        }}

        if (payload.status === "pending" || payload.status === "running") {{
          messageText.textContent = "任务处理中，请稍候。";
          setTimeout(pollStatus, 3000);
          return;
        }}

        if (payload.status === "succeeded") {{
          messageText.textContent = "处理完成，可以下载。";
          errorText.textContent = "";
          showDownload();
          return;
        }}

        if (payload.status === "failed") {{
          messageText.textContent = "";
          errorText.textContent = payload.error || "处理失败，请重新上传或稍后再试。";
        }}
      }} catch (error) {{
        messageText.textContent = "连接波动，正在重试。";
        errorText.textContent = "";
        setTimeout(pollStatus, 3000);
      }}
    }}

    pollStatus();
  </script>
</body>
</html>"""


async def create_task_from_request(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    cleanup_expired_tasks()
    body = await request.body()
    fields, files = parse_multipart_request(body, request.headers.get("content-type", ""))
    access_password = fields.get("access_password", "")
    verify_access_password(access_password)

    file_payload = files.get("file")
    if file_payload is None:
        raise HTTPException(status_code=400, detail="missing file field")

    filename = file_payload["filename"] or ""
    if not filename.lower().endswith(".epub"):
        raise HTTPException(status_code=400, detail="only .epub files are supported")

    content = file_payload["content"]
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


@APP.post("/auth/check")
def check_auth(access_password: str = Form("")) -> dict:
    verify_access_password(access_password)
    return {"status": "ok"}


@APP.post("/tasks")
async def create_task(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    return await create_task_from_request(request, background_tasks)


@APP.post("/submit")
async def submit_task(
    request: Request,
    background_tasks: BackgroundTasks,
) -> HTMLResponse:
    status = await create_task_from_request(request, background_tasks)
    return HTMLResponse(render_task_page(status["task_id"]))


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
