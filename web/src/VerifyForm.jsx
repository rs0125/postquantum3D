import React, { useEffect, useRef, useState } from 'react';
import { ACCEPT, apiRequest, download, readVerificationKit, validateMesh } from './api.js';

export default function VerifyForm({ seed, onGoToSign }) {
  const [files, setFiles] = useState({mesh: null, signature: null, public_key: null});
  const [mode, setMode] = useState('kit');
  const [kitName, setKitName] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [readingKit, setReadingKit] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(null);
  const kitRead = useRef(0);
  const resultRef = useRef(null);
  useEffect(() => () => {request.current?.abort(); kitRead.current += 1;}, []);
  useEffect(() => {
    if (!seed) return;
    request.current?.abort(); request.current = null; kitRead.current += 1;
    setFiles(seed); setKitName('Signature from your current signing result');
    setMode('kit'); setResult(null); setError(''); setBusy(false); setReadingKit(false);
  }, [seed]);

  const clearResult = () => {setResult(null); setError('');};
  const cancel = () => {request.current?.abort(); request.current = null; setBusy(false);};
  const changeMode = next => {
    kitRead.current += 1; setReadingKit(false); setMode(next); setKitName('');
    setFiles(current => ({...current, signature: null, public_key: null})); clearResult();
  };
  const selectFile = (name, file) => {
    clearResult();
    if (name === 'mesh' && file) {
      try {validateMesh(file);} catch (failure) {setError(failure.message); setFiles(current => ({...current, mesh: null})); return;}
    }
    setFiles(current => ({...current, [name]: file}));
  };
  async function selectKit(file) {
    const sequence = ++kitRead.current;
    clearResult(); setKitName(''); setFiles(current => ({...current, signature: null, public_key: null}));
    if (!file) {setReadingKit(false); return;}
    setReadingKit(true);
    try {
      const extracted = await readVerificationKit(file);
      if (sequence === kitRead.current) {setFiles(current => ({...current, ...extracted})); setKitName(file.name);}
    } catch (failure) {if (sequence === kitRead.current) setError(failure.message);}
    finally {if (sequence === kitRead.current) setReadingKit(false);}
  }

  async function submit(event) {
    event.preventDefault(); clearResult();
    let controller;
    try {
      validateMesh(files.mesh);
      if (!files.signature || !files.public_key) throw new Error('Choose a verification kit, or provide the signature and public key separately.');
      if (files.signature.size > 16 * 1024 || files.public_key.size > 4096) throw new Error('The signature or public key file is too large. Choose the files saved after signing.');
      const body = new FormData(); Object.entries(files).forEach(([name, file]) => body.append(name, file));
      controller = new AbortController(); request.current = controller; setBusy(true);
      const response = await apiRequest('/api/verify', {method: 'POST', body, signal: controller.signal});
      if (request.current === controller) {
        setResult(response);
        requestAnimationFrame(() => resultRef.current?.focus({preventScroll: false}));
      }
    } catch (failure) {
      if (failure.name !== 'AbortError' && (!controller || request.current === controller)) setError(failure.message);
    } finally {if (controller && request.current === controller) {request.current = null; setBusy(false);}}
  }

  const ready = Object.values(files).every(Boolean);
  const picker = (name, title, accept, hint, displayName, onChange) => <div className="file-field" key={name}>
    <label className="field-label" htmlFor={`verify-${name}`}>{title}</label>
    <div className={`file-picker ${displayName ? 'selected' : ''}`}>
      <span className="picker-icon" aria-hidden="true">{displayName ? '✓' : '↥'}</span>
      <strong>{displayName || 'Choose file'}</strong><small>{hint}</small>
      <input id={`verify-${name}`} type="file" accept={accept} aria-label={name === 'mesh' ? 'Mesh file' : name === 'kit' ? 'Verification kit' : name === 'signature' ? 'Signature' : 'Public key'} disabled={busy || readingKit} onChange={event => {const file = event.target.files[0] || null; event.target.value = ''; onChange(file);}} />
    </div>
    {displayName && <button type="button" className="text-button remove-file" disabled={busy || readingKit} onClick={() => onChange(null)}>Remove {name === 'public_key' ? 'public key' : name}</button>}
  </div>;

  return <section className="panel verify-existing" id="verify-existing">
    <div className="panel-heading"><h2>Choose the files to check</h2><span className="file-badge">No new signature is created</span></div>
    <form onSubmit={submit}>
      <fieldset className="verification-mode" disabled={busy || readingKit}><legend>How did you save the signature?</legend><label><input type="radio" name="verification-mode" value="kit" checked={mode === 'kit'} onChange={() => changeMode('kit')} /> A verification kit <span>Recommended</span></label><label><input type="radio" name="verification-mode" value="separate" checked={mode === 'separate'} onChange={() => changeMode('separate')} /> Separate signature and key files</label></fieldset>
      <div className={`verification-inputs ${mode === 'kit' ? 'two-fields' : ''}`}>
        {picker('mesh', '1. Mesh to verify', ACCEPT, 'The original mesh or a version you want to check.', files.mesh?.name, file => selectFile('mesh', file))}
        {mode === 'kit' ? picker('kit', '2. Saved verification kit', '.json', 'The .verification-kit.json file saved after signing.', kitName, selectKit) : <>
          {picker('signature', '2. Signature file', '.json', 'The original .sig.json file.', files.signature?.name, file => selectFile('signature', file))}
          {picker('public_key', '3. Public key', '.key', 'The matching public.key file.', files.public_key?.name, file => selectFile('public_key', file))}
        </>}
      </div>
      <div className="form-actions"><button className="button primary" disabled={busy || readingKit || !ready} type="submit">{busy ? <><span className="spinner" /> Checking signature…</> : 'Verify mesh →'}</button>{busy && <button type="button" className="button secondary" onClick={cancel}>Cancel request</button>}<span role="status">{readingKit ? 'Reading your verification kit…' : busy ? 'Checking the mesh against your saved signature.' : ready ? 'Ready to verify. Your files will not be changed.' : mode === 'kit' ? 'Choose a mesh and its verification kit to continue.' : 'Choose all three files to continue.'}</span></div>
      {error && <div className="error-message" role="alert">{error}</div>}
      {result && <div className="existing-result" ref={resultRef} tabIndex={-1} aria-label="Verification result"><div className={`status-banner ${result.verified ? '' : 'invalid'}`}><div className="status-symbol" aria-hidden="true">{result.verified ? '✓' : '×'}</div><div><strong>{result.verified ? 'Signature verified' : 'Verification failed'}</strong><p>{result.filename} · Checked in {result.elapsedMs.toFixed(1)} ms</p></div></div><p className="result-explanation">{result.verified ? 'This mesh matches the saved fingerprint, and the signature is valid for the supplied public key.' : !result.fingerprintMatches ? 'The mesh fingerprint does not match the one in your signature file. Make sure you chose the correct mesh and its original signature.' : 'The fingerprint matches, but the signature is invalid. Check that you chose the matching public key and an unchanged signature file.'}</p><details className="hash-details"><summary>Compare the two fingerprints</summary><div className="verification-hashes"><div><span className="label">Uploaded mesh</span><code>{result.hash}</code></div><div><span className="label">Saved signature</span><code>{result.signedHash}</code></div></div></details><button type="button" className="button secondary" onClick={() => download('verification-report.json', result)}>↓ Download verification report</button></div>}
      <div className="verify-help"><strong>Don’t have a signature yet?</strong><p>Sign your mesh first, then save its verification kit.</p><button type="button" className="text-button" onClick={onGoToSign}>Go to Sign a mesh →</button></div>
    </form>
  </section>;
}
