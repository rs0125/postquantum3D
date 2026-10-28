export const MAX_BYTES = 20 * 1024 * 1024;
export const ACCEPT = '.obj,.stl,.ply,.glb';

export function validateMesh(file) {
  if (!file) throw new Error('Choose a mesh file first.');
  if (!/\.(obj|stl|ply|glb)$/i.test(file.name)) throw new Error('Choose an OBJ, STL, PLY, or self-contained GLB mesh.');
  if (!file.size) throw new Error('The selected file is empty.');
  if (file.size > MAX_BYTES) throw new Error('Choose a mesh smaller than 20 MB.');
}

export async function apiRequest(path, options = {}) {
  let response;
  try { response = await fetch(path, options); }
  catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach FastAPI. Start the backend on port 8000 and try again.');
  }
  const json = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = json?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}). Check the backend and try again.`);
  }
  if (!json) throw new Error('The server returned an unexpected response. Check that FastAPI is running.');
  return json;
}

export function download(filename, content, type = 'application/json') {
  const payload = type === 'application/json' ? JSON.stringify(content, null, 2) : content;
  const url = URL.createObjectURL(new Blob([payload], {type}));
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function publicKeyBytes(base64) { return Uint8Array.from(atob(base64), character => character.charCodeAt(0)); }

export function verificationFiles(signature, publicKey) {
  return {
    signature: new File([JSON.stringify(signature)], 'signature.sig.json', {type: 'application/json'}),
    public_key: new File([publicKeyBytes(publicKey)], 'public.key', {type: 'application/octet-stream'}),
  };
}

export async function readVerificationKit(file) {
  if (!file || file.size > 32 * 1024) throw new Error('Choose a verification kit downloaded from this app (up to 32 KB).');
  try {
    const kit = JSON.parse(await file.text());
    if (kit.format !== 'postquantum3d-verification-kit' || kit.version !== 1 ||
        kit.signature?.algorithm !== 'ML-DSA-44' || typeof kit.publicKey !== 'string' ||
        publicKeyBytes(kit.publicKey).length !== 1312) throw new Error('Invalid kit');
    return verificationFiles(kit.signature, kit.publicKey);
  } catch { throw new Error('This is not a valid verification kit. Choose the kit saved after signing, or switch to separate signature and key files.'); }
}
