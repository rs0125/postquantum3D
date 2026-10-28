"""Real crypto integration tests for the upload API (no mocked verdicts)."""

import base64
import json
import shutil
import sys
from pathlib import Path

import pytest
import trimesh
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api.main import app
from api.processing import MAX_FILE_BYTES
from postquantum3d import generate_keys, sign_mesh, verify_mesh


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as session:
        yield session


@pytest.fixture(scope="module")
def signed(client):
    response = client.post("/api/process", files={"file": ("suzanne.obj", (ROOT / "test_meshes/suzanne.obj").read_bytes())})
    assert response.status_code == 200, response.text
    return response.json()


def verify_files(signed, content=None, sidecar=None, public_key=None):
    return {
        "mesh": ("suzanne.obj", content if content is not None else (ROOT / "test_meshes/suzanne.obj").read_bytes()),
        "signature": ("suzanne.obj.sig.json", json.dumps(sidecar if sidecar is not None else signed["sidecar"]).encode()),
        "public_key": ("public.key", public_key if public_key is not None else base64.b64decode(signed["publicKey"])),
    }


def test_upload_runs_real_scenarios(signed):
    assert signed["vertexCount"] == 507
    assert signed["signatureBytes"] == 2420
    assert len(base64.b64decode(signed["publicKey"])) == 1312
    assert "private" not in json.dumps(signed).lower()
    assert len(signed["checks"]) == 5
    assert all(check["actual"] == check["expected"] for check in signed["checks"])
    assert signed["scenarios"]["original"]["hash"] == signed["scenarios"]["transformed"]["hash"]
    assert signed["scenarios"]["original"]["hash"] != signed["scenarios"]["tampered"]["hash"]
    assert len(signed["scenarios"]["original"]["vertices"]) == signed["vertexCount"]


def test_signature_works_with_existing_python_api(signed, tmp_path):
    mesh = tmp_path / "suzanne.obj"
    shutil.copyfile(ROOT / "test_meshes/suzanne.obj", mesh)
    sidecar = tmp_path / "signature.json"
    sidecar.write_text(json.dumps(signed["sidecar"]))
    key = tmp_path / "public.key"
    key.write_bytes(base64.b64decode(signed["publicKey"]))
    assert verify_mesh(mesh, key, sidecar)


def test_existing_python_signature_works_with_api(client, tmp_path):
    mesh = tmp_path / "suzanne.obj"
    shutil.copyfile(ROOT / "test_meshes/suzanne.obj", mesh)
    generate_keys(tmp_path / "keys")
    sidecar = sign_mesh(mesh, tmp_path / "keys/private.key")
    response = client.post("/api/verify", files={
        "mesh": (mesh.name, mesh.read_bytes()), "signature": (sidecar.name, sidecar.read_bytes()),
        "public_key": ("public.key", (tmp_path / "keys/public.key").read_bytes()),
    })
    assert response.status_code == 200, response.text
    assert response.json()["verified"] is True


def test_verify_original_and_tampered_mesh(client, signed):
    response = client.post("/api/verify", files=verify_files(signed))
    assert response.status_code == 200 and response.json()["verified"] is True
    mesh = trimesh.load(ROOT / "test_meshes/suzanne.obj", force="mesh")
    mesh.vertices[0] += [1, 0, 0]
    response = client.post("/api/verify", files=verify_files(signed, content=mesh.export(file_type="obj").encode()))
    assert response.status_code == 200 and response.json()["verified"] is False


def test_wrong_key_and_modified_signature_are_rejected(client, signed, tmp_path):
    generate_keys(tmp_path / "other")
    response = client.post("/api/verify", files=verify_files(signed, public_key=(tmp_path / "other/public.key").read_bytes()))
    assert response.status_code == 200 and response.json()["verified"] is False
    sidecar = dict(signed["sidecar"])
    signature = bytearray(base64.b64decode(sidecar["signature_b64"]))
    signature[0] ^= 1
    sidecar["signature_b64"] = base64.b64encode(signature).decode()
    response = client.post("/api/verify", files=verify_files(signed, sidecar=sidecar))
    assert response.status_code == 200 and response.json()["verified"] is False


@pytest.mark.parametrize("field,value", [("algorithm", "other"), ("signature_b64", "bad%%%"), ("geometric_hash", "short")])
def test_malformed_sidecar_returns_useful_error(client, signed, field, value):
    sidecar = dict(signed["sidecar"])
    sidecar[field] = value
    response = client.post("/api/verify", files=verify_files(signed, sidecar=sidecar))
    assert response.status_code == 422
    assert "valid ML-DSA-44" in response.json()["detail"]


@pytest.mark.parametrize("filename,content", [("file.txt", b"data"), ("empty.obj", b""), ("bad.obj", b"not a mesh"), ("bad.glb", b"not a glb")])
def test_invalid_uploads(client, filename, content):
    response = client.post("/api/process", files={"file": (filename, content)})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


@pytest.mark.parametrize("extension", ["obj", "stl", "ply", "glb"])
def test_supported_mesh_formats(client, extension):
    mesh = trimesh.creation.box(extents=[1, 2, 3])
    content = mesh.export(file_type=extension)
    if isinstance(content, str):
        content = content.encode()
    response = client.post("/api/process", files={"file": (f"box.{extension}", content)})
    assert response.status_code == 200, response.text
    assert response.json()["scenarios"]["original"]["verified"] is True


def test_size_limit_and_filename_sanitization(client):
    response = client.post("/api/process", content=b"x", headers={"content-length": str(MAX_FILE_BYTES + 128 * 1024)})
    assert response.status_code == 413
    content = (ROOT / "test_meshes/suzanne.obj").read_bytes()
    response = client.post("/api/process", files={"file": ("../../nested/custom.obj", content)})
    assert response.status_code == 200
    assert response.json()["filename"] == "custom.obj"


def test_degenerate_large_mesh_is_bounded(client):
    mesh = trimesh.creation.icosphere(subdivisions=4)
    response = client.post("/api/process", files={"file": ("sphere.ply", mesh.export(file_type="ply"))})
    assert response.status_code == 422
    assert "pairwise-distance" in response.json()["detail"]


def test_downloadable_samples_and_no_arbitrary_paths(client):
    assert client.get("/api/health").json()["status"] == "ready"
    assert client.get("/api/samples/suzanne.obj").status_code == 200
    assert client.get("/api/samples/private.key").status_code == 404
    assert client.get("/api/not-a-route").status_code == 404
