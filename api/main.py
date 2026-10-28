"""Run: python -m uvicorn api.main:app --host 127.0.0.1 --port 8000"""

import logging
import threading
from pathlib import Path

import oqs
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .processing import (
    ALGORITHM, FORMATS, MAX_FILE_BYTES, MAX_VERTICES, MAX_FACES,
    MAX_DISTANCE_VERTICES, MeshInputError, ROOT, process_mesh, verify_upload,
)

logger = logging.getLogger(__name__)
capacity = threading.BoundedSemaphore(2)


class UploadLimitMiddleware:
    """Bound the complete request before multipart parsing, including chunked bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        limit = MAX_FILE_BYTES + 64 * 1024
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length."}, 400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({"detail": "Upload exceeds the 20 MB mesh limit."}, 413)(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > limit:
                return await JSONResponse({"detail": "Upload exceeds the 20 MB mesh limit."}, 413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(chunks)

        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)


def read_upload(upload, limit):
    content = upload.file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"{Path(upload.filename or 'File').name} exceeds its upload limit.")
    return content


def run_processing(action):
    if not capacity.acquire(blocking=False):
        raise HTTPException(503, "Two meshes are already processing. Try again in a moment.")
    try:
        return action()
    except MeshInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Mesh processing failed")
        raise HTTPException(500, "Processing failed. Check the FastAPI console and try another mesh.") from exc
    finally:
        capacity.release()


app = FastAPI(title="postquantum3D API", version="0.1.0", description="Local mesh fingerprinting, ML-DSA-44 signing, and verification.")
app.add_middleware(UploadLimitMiddleware)


@app.get("/api/health")
def health():
    available = ALGORITHM in oqs.get_enabled_sig_mechanisms()
    return JSONResponse({"status": "ready" if available else "unavailable", "algorithm": ALGORITHM,
                         "formats": sorted(FORMATS), "maxFileBytes": MAX_FILE_BYTES,
                         "maxVertices": MAX_VERTICES, "maxFaces": MAX_FACES,
                         "maxDistanceVertices": MAX_DISTANCE_VERTICES}, status_code=200 if available else 503)


@app.post("/api/process")
def process(file: UploadFile):
    """Upload, fingerprint, sign, and execute five real verification scenarios."""
    content = read_upload(file, MAX_FILE_BYTES)
    return run_processing(lambda: process_mesh(content, file.filename))


@app.post("/api/verify")
def verify(mesh: UploadFile, signature: UploadFile, public_key: UploadFile):
    """Verify an uploaded mesh against an existing sidecar and raw public key."""
    content = read_upload(mesh, MAX_FILE_BYTES)
    sidecar = read_upload(signature, 16 * 1024)
    key = read_upload(public_key, 4 * 1024)
    return run_processing(lambda: verify_upload(content, mesh.filename, sidecar, key))


@app.get("/api/samples/{filename}")
def sample(filename: str):
    if filename not in {"suzanne.obj", "teapot.obj"}:
        raise HTTPException(404, "Sample not found.")
    return FileResponse(ROOT / "test_meshes" / filename, filename=filename, media_type="application/octet-stream")


@app.get("/", include_in_schema=False)
def index():
    index_file = ROOT / "web/dist/index.html"
    if not index_file.exists():
        return JSONResponse({"message": "Build the frontend with: npm --prefix web run build", "apiDocs": "/docs"})
    return FileResponse(index_file)


app.mount("/assets", StaticFiles(directory=ROOT / "web/dist/assets", check_dir=False), name="assets")
