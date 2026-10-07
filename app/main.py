"""FastAPI application: upload a DBF (with optional memo file) and get JSON back."""

from __future__ import annotations

import codecs
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .converter import ConvertOptions, describe, iter_records, open_dbf, stream_json

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
MEMO_EXTENSIONS = {".dbt", ".fpt"}

app = FastAPI(title="DBF → JSON", version="1.0.0")


def _safe_stem(filename: str | None) -> str:
    stem = Path(filename or "table").stem
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return cleaned or "table"


async def _save_upload(upload: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "File too large (max 500 MB).")
            out.write(chunk)


async def _prepare(dbf: UploadFile, memo: UploadFile | None) -> tuple[Path, Path, str]:
    """Store uploads in a temp dir so dbfread can find the memo file next to the DBF."""
    if not dbf.filename or Path(dbf.filename).suffix.lower() != ".dbf":
        raise HTTPException(400, "Please upload a file with the .dbf extension.")
    stem = _safe_stem(dbf.filename)
    workdir = Path(tempfile.mkdtemp(prefix="dbf2json_"))
    try:
        dbf_path = workdir / f"{stem}.dbf"
        await _save_upload(dbf, dbf_path)
        if memo is not None and memo.filename:
            ext = Path(memo.filename).suffix.lower()
            if ext not in MEMO_EXTENSIONS:
                raise HTTPException(400, "Memo file must be .dbt or .fpt.")
            await _save_upload(memo, workdir / f"{stem}{ext}")
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return workdir, dbf_path, stem


def _options(encoding: str, include_deleted: bool, lowercase: bool,
             include_schema: bool, pretty: bool) -> ConvertOptions:
    enc = encoding.strip() or None
    if enc:
        try:
            codecs.lookup(enc)
        except LookupError:
            raise HTTPException(400, f"Unknown encoding: {enc}")
    return ConvertOptions(
        encoding=enc,
        include_deleted=include_deleted,
        lowercase_names=lowercase,
        include_schema=include_schema,
        indent=2 if pretty else None,
    )


@app.post("/api/inspect")
async def inspect(
    dbf: UploadFile = File(...),
    memo: UploadFile | None = File(None),
    encoding: str = Form(""),
    include_deleted: bool = Form(False),
    lowercase: bool = Form(False),
    preview_rows: int = Form(50),
):
    """Return table metadata plus the first N records for preview."""
    workdir, dbf_path, _ = await _prepare(dbf, memo)
    try:
        opts = _options(encoding, include_deleted, lowercase, True, False)
        table = open_dbf(dbf_path, opts)
        info = describe(table)
        preview = []
        for row in iter_records(table, opts):
            preview.append(row)
            if len(preview) >= max(1, min(preview_rows, 500)):
                break
        info["preview"] = preview
        return JSONResponse(info)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not read DBF file: {exc}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/convert")
async def convert(
    dbf: UploadFile = File(...),
    memo: UploadFile | None = File(None),
    encoding: str = Form(""),
    include_deleted: bool = Form(False),
    lowercase: bool = Form(False),
    include_schema: bool = Form(True),
    pretty: bool = Form(True),
):
    """Convert the DBF and stream the resulting JSON file as a download."""
    workdir, dbf_path, stem = await _prepare(dbf, memo)
    try:
        opts = _options(encoding, include_deleted, lowercase, include_schema, pretty)
        # Read header now so a broken file fails with a clean error, not mid-stream
        open_dbf(dbf_path, opts)
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(422, f"Could not read DBF file: {exc}") from exc

    return StreamingResponse(
        stream_json(dbf_path, opts),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
        background=BackgroundTask(shutil.rmtree, workdir, ignore_errors=True),
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
