# Live React + FastAPI dashboard

The React frontend is in `web/`, and the FastAPI backend is in `api/`.

## Run the application

From the repository root, using Python 3.10+ and Node 22.12+:

```bash
python -m pip install -r api/requirements.txt
npm --prefix web ci
npm --prefix web run build
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. FastAPI serves the built React application and the API
from the same origin. No second server is needed for a demonstration.

The Python dependencies require an installed system **liboqs** compatible with
`liboqs-python==0.12.0`, with ML-DSA-44 enabled. This version is the working version
in the existing project environment. If you already use another working liboqs /
Python-binding pair, retain that matched pair and install the other requirements.

For frontend development with hot reload, keep FastAPI running and use a second terminal:

```bash
npm --prefix web run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` requests to port 8000.
For Python hot reload, add `--reload` to the Uvicorn command.

## Use the dashboard

1. Open **Sign a mesh**. Drop an OBJ, STL, PLY, or self-contained GLB file, or choose a sample.
2. The server loads the actual mesh, runs `MeshCanonicalizer`, generates an ML-DSA-44
   keypair, signs the UTF-8 hexadecimal fingerprint, and verifies it.
3. The server also runs four additional checks: an in-memory similarity transform,
   a controlled geometry edit, a modified signature, and a wrong public key.
4. Switch between original, transformed, and tampered previews. The displayed
   verdicts and timing measurements come from the server; failed expectations
   are displayed as unexpected results.
5. Select **Save verification kit** to download one JSON file containing the
   original signature and public key. Keep it with the original mesh. Separate
   signature/key downloads and a report are available in the expandable section.
   A fresh keypair is generated for every processing run; the secret key is discarded.
6. Open **Verify a mesh** and choose the mesh plus its saved verification kit.
   Existing `.sig.json` and raw `public.key` files work in the **Separate signature
   and key files** mode. **Verify this mesh now** fills in the current signing
   result so you can try verification immediately. This operation does not sign the mesh.

Signing and verification have separate screens, and switching between them retains
the current results and file selections. The signing screen follows upload → review
→ save, explains expected tamper rejections, and keeps technical details collapsed.
Main controls have at least 44-pixel touch targets; navigation labels remain visible
on mobile, and the check table becomes labelled rows on small screens.

“Cancel” stops the browser request and clears its loading state. A calculation
already executing in Python may finish before releasing its worker slot.

The 3D view uses WebGL. Drag to rotate, scroll to zoom, or focus it and use arrow
keys / + / −. Visible zoom buttons also work on touchscreens. The Y up / Z up
control changes only the viewing orientation. Preview
coordinates are centered and fitted for display; hashing always uses the loaded
mesh at full precision. Large wireframe views sample triangles for rendering;
fingerprinting and solid rendering use the full accepted mesh.

## API

Interactive API documentation: **http://127.0.0.1:8000/docs**.

| Endpoint | Input | Output |
| --- | --- | --- |
| `GET /api/health` | None | Crypto availability and upload limits |
| `POST /api/process` | Multipart `file` | Geometry, signatures, public key, hashes, five checks and timings |
| `POST /api/verify` | Multipart `mesh`, `signature`, `public_key` | Actual signature verdict and compared fingerprints |
| `GET /api/samples/{filename}` | `suzanne.obj` or `teapot.obj` | Sample mesh |

```bash
curl -F 'file=@test_meshes/suzanne.obj' http://127.0.0.1:8000/api/process
curl -F 'mesh=@model.obj' -F 'signature=@model.obj.sig.json' -F 'public_key=@public.key' http://127.0.0.1:8000/api/verify
```

## Scope and limits

- This is a **local development application**, with no user accounts or ownership
  certificates. It is not configured for public internet deployment.
- Mesh uploads are limited to 20 MB, 50,000 loaded vertices and 100,000 triangles.
  Two processing requests can execute concurrently. Additional requests receive
  a retryable error. The complete multipart body is also bounded before parsing.
- The existing canonicalizer's pairwise-distance fallback is quadratic; the API
  limits that branch to 1,500 vertices without changing its algorithm.
- Uploaded mesh data is processed in memory and not saved by the application.
  The framework may spool multipart files temporarily while receiving them.
- External mesh dependencies are not resolved. Use self-contained GLB rather than
  a `.gltf` file with separate buffers. Textures and materials are not authenticated.
- The canonical fingerprint covers the loaded vertex representation, not face
  connectivity, metadata, materials, textures, or creator identity.
- Transform checks operate **in memory**, not through a DCC or format round trip.
  Loaders can merge vertices on re-export/re-import, changing the fingerprint.
- Red highlighting identifies the region edited by this demonstration. It is not
  an algorithm for locating unknown tampering.
- The signature format is interoperable with `src/postquantum3d/sign.py`. Only the
  geometry fingerprint is cryptographically signed. The verification endpoint
  also requires the sidecar's fingerprint field to match the computed one.

## Validation

```bash
python -m pip install pytest httpx
python -m pytest tests/test_api.py -q
npm --prefix web run build
```

The API integration tests exercise real ML-DSA signatures, both directions of
interoperability with the existing Python API, supported mesh formats, incorrect
keys, modified geometry/signatures, invalid files, and size/fallback limits.

Framework references: [FastAPI multipart uploads](https://fastapi.tiangolo.com/tutorial/request-files/),
[React effect cleanup](https://react.dev/reference/react/useEffect), and
[Trimesh loading](https://trimesh.org/trimesh.exchange.load.html).
