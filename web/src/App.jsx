import React, { useEffect, useRef, useState } from 'react';
import MeshViewer from './MeshViewer.jsx';
import VerifyForm from './VerifyForm.jsx';
import { ACCEPT, apiRequest, download, publicKeyBytes, validateMesh, verificationFiles } from './api.js';

const explanations = {
  original: 'This is your original upload. Select another version to see how its verification result changes.',
  transformed: 'A copy rotated 35°, scaled 1.5× and moved. This test checks whether its fingerprint stays the same.',
  tampered: 'A deliberately edited copy. The red region shows where this demo changed the geometry.',
};

export default function App() {
  const [result, setResult] = useState(null);
  const [view, setView] = useState('sign');
  const [verifySeed, setVerifySeed] = useState(null);
  const [saved, setSaved] = useState(false);
  const [scenario, setScenario] = useState('original');
  const [busy, setBusy] = useState(false);
  const [uploadName, setUploadName] = useState('');
  const [error, setError] = useState('');
  const [health, setHealth] = useState('connecting');
  const [dragging, setDragging] = useState(false);
  const [notification, setNotification] = useState('');
  const fileInput = useRef(null);
  const request = useRef(null);
  const notificationTimer = useRef(null);
  const originalFile = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest('/api/health', {signal: controller.signal}).then(() => setHealth('ready')).catch(failure => {if (failure.name !== 'AbortError') setHealth('offline');});
    return () => {controller.abort(); request.current?.abort(); clearTimeout(notificationTimer.current);};
  }, []);

  const notify = message => {
    clearTimeout(notificationTimer.current); setNotification(message);
    notificationTimer.current = setTimeout(() => setNotification(''), 3000);
  };

  async function process(file, controller = new AbortController()) {
    try { validateMesh(file); } catch (failure) { setError(failure.message); return; }
    request.current?.abort(); request.current = controller;
    originalFile.current = file;
    setBusy(true); setError(''); setResult(null); setScenario('original'); setUploadName(file.name); setSaved(false);
    const body = new FormData(); body.append('file', file);
    try {
      const response = await apiRequest('/api/process', {method: 'POST', body, signal: controller.signal});
      if (request.current === controller) { setResult(response); setHealth('ready'); }
    } catch (failure) {
      if (request.current === controller && failure.name !== 'AbortError') setError(failure.message);
    } finally { if (request.current === controller) { setBusy(false); request.current = null; } }
  }

  async function sample(filename) {
    const controller = new AbortController(); request.current?.abort(); request.current = controller;
    setBusy(true); setError(''); setResult(null); setUploadName(filename);
    try {
      const response = await fetch(`/api/samples/${filename}`, {signal: controller.signal});
      if (!response.ok) throw new Error('Could not load the sample. Check that FastAPI is running.');
      const file = new File([await response.blob()], filename, {type: 'application/octet-stream'});
      if (request.current === controller) { request.current = null; await process(file, controller); }
    } catch (failure) {
      if (request.current === controller && failure.name !== 'AbortError') setError(failure.message || 'Could not reach FastAPI.');
    } finally { if (request.current === controller) { setBusy(false); request.current = null; } }
  }

  function cancel() { request.current?.abort(); request.current = null; setBusy(false); setUploadName(''); notify('Request cancelled. You can choose another mesh.'); }
  function navigate(next) {
    setView(next);
    window.scrollTo({top: 0, behavior: 'instant'});
    requestAnimationFrame(() => document.getElementById('main-content')?.focus({preventScroll: true}));
  }
  async function reconnect() { setHealth('connecting'); try { await apiRequest('/api/health'); setHealth('ready'); } catch { setHealth('offline'); } }
  function saveKit() { download(`${result.filename}.verification-kit.json`, {format: 'postquantum3d-verification-kit', version: 1, assetName: result.filename, signature: result.sidecar, publicKey: result.publicKey}); setSaved(true); notify('Verification kit downloaded. Keep it with the original mesh.'); }
  function verifyCurrent() { setVerifySeed({mesh: originalFile.current, ...verificationFiles(result.sidecar, result.publicKey)}); navigate('verify'); }
  function drop(event) {
    event.preventDefault(); setDragging(false);
    if (busy) return;
    if (event.dataTransfer.files.length !== 1) {setError('Drop one mesh at a time.'); return;}
    process(event.dataTransfer.files[0]);
  }

  const current = result?.scenarios[scenario];
  const valid = current?.verified === true;
  const unavailable = current?.verified == null;
  const matching = current?.hash && current.hash === result?.scenarios.original.hash;
  const correctChecks = result?.checks.filter(check => check.actual !== null && check.actual === check.expected).length || 0;
  const report = () => {
    const {faces, changedVertices, scenarios, ...metadata} = result;
    download(`${result.filename}-report.json`, {...metadata, scenarios: Object.fromEntries(Object.entries(scenarios).map(([name, {vertices, ...summary}]) => [name, summary])), transformation: 'In-memory: 35 degrees around Z, 1.5 uniform scale, translation [2, -1, 0.5]'});
  };

  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="sidebar">
      <a className="brand" href="#" onClick={event => {event.preventDefault(); navigate('sign');}}><span className="brand-icon" aria-hidden="true">⬡</span><span>postquantum<span className="lime">3D</span><small>3D asset verification</small></span></a>
      <div className="nav-label">Your workspace</div>
      <nav aria-label="Main navigation">
        <button className={`nav-link ${view === 'sign' ? 'active' : ''}`} aria-current={view === 'sign' ? 'page' : undefined} onClick={() => navigate('sign')}><span aria-hidden="true">＋</span> Sign a mesh</button>
        <button className={`nav-link ${view === 'verify' ? 'active' : ''}`} aria-current={view === 'verify' ? 'page' : undefined} onClick={() => navigate('verify')}><span aria-hidden="true">✓</span> Verify a mesh</button>
      </nav>
      <div className="sidebar-project"><span className="project-mark">P1</span><div>B.Tech Project 1<small>Post-quantum signatures</small></div></div>
      <div className="sidebar-note"><span className={`live-dot ${health === 'ready' ? '' : 'offline'}`} />{health === 'ready' ? 'Server connected' : health === 'connecting' ? 'Connecting…' : 'Server unavailable'}<small>Your meshes are processed<br />on your local Python server.</small>{health === 'offline' && <button className="text-button" onClick={reconnect}>Check connection again</button>}</div>
    </aside>
    <main id="main-content" tabIndex={-1} aria-label={view === 'sign' ? 'Sign a mesh workspace' : 'Verify a mesh workspace'}>
      <header className="topbar"><span>Workspace <span className="crumb-divider">/</span> <strong>{view === 'sign' ? 'Sign a mesh' : 'Verify a mesh'}</strong></span><span className="connection-status"><span className={`live-dot ${health === 'ready' ? '' : 'offline'}`} />{health === 'ready' ? 'Connected' : health === 'offline' ? 'Server offline' : 'Connecting…'}</span></header>
      {health === 'offline' && <div className="error-message connection-error" role="status"><div><strong>The processing server is unavailable.</strong><p>Start FastAPI on port 8000, then check the connection again.</p></div><button className="button secondary" onClick={reconnect}>Retry connection</button></div>}
      <div hidden={view !== 'sign'}>
        <section className="page-heading"><div><div className="eyebrow">Sign a new asset</div><h1>Sign and check your 3D mesh</h1><p>Create a signature for your mesh and see whether geometry changes can be detected.</p></div></section>
        <ol className="workflow-steps" aria-label="Signing steps"><li className={!result ? 'current' : 'complete'}><span>{result ? '✓' : '1'}</span>Upload a mesh</li><li className={result ? 'complete' : ''}><span>{result ? '✓' : '2'}</span>Review results</li><li className={saved ? 'complete' : result ? 'current' : ''}><span>{saved ? '✓' : '3'}</span>Save your kit</li></ol>
        <section className={`upload-zone ${dragging ? 'dragging' : ''} ${busy ? 'processing' : ''}`} onDragOver={event => {event.preventDefault(); if (!busy) setDragging(true);}} onDragLeave={event => {if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false);}} onDrop={drop} aria-label="Mesh upload" aria-busy={busy}>
          <span className="upload-icon" aria-hidden="true">{busy ? <span className="spinner" /> : '↥'}</span>
          <div className="upload-copy" role="status"><strong>{busy ? `Processing ${uploadName}…` : result ? 'Want to sign another mesh?' : 'Choose a mesh or drop it here'}</strong><p>{busy ? 'Loading geometry, creating a signature and checking the results. This may take a moment.' : 'OBJ, STL, PLY or GLB · Up to 20 MB and 50,000 vertices'}</p>{!busy && <span className="upload-explanation">Signing and checks start automatically after you select a file.</span>}</div>
          <input ref={fileInput} id="mesh-upload" type="file" accept={ACCEPT} className="sr-only" aria-label="Upload mesh" disabled={busy} tabIndex={-1} onChange={event => {const file = event.target.files[0]; event.target.value = ''; if (file) process(file);}} />
          {busy ? <button className="button secondary" onClick={cancel}>Cancel request</button> : <button className="button primary" onClick={() => fileInput.current.click()}>{result ? 'Choose another mesh' : 'Choose mesh'} <span aria-hidden="true">＋</span></button>}
        </section>
        <div className="upload-footnote"><span>No mesh handy? Try a sample:</span><button disabled={busy} onClick={() => sample('suzanne.obj')}>Suzanne</button><button disabled={busy} onClick={() => sample('teapot.obj')}>Utah Teapot</button></div>
        {error && <div className="error-message" role="alert"><span>{error}</span><button className="text-button" onClick={() => setError('')}>Dismiss</button></div>}
        {result ? <>
          <div className="results-heading"><div><h2>Your mesh is ready to review</h2><p><strong>{result.filename}</strong> · {result.vertexCount.toLocaleString()} vertices · {(result.elapsedMs / 1000).toFixed(2)} seconds</p></div><span className={`check-summary ${correctChecks === 5 ? '' : 'warning'}`}>{correctChecks === 5 ? '✓' : '△'} {correctChecks} of 5 checks as expected</span></div>
          <section className="workspace">
            <article className="panel viewer-panel"><div className="panel-heading"><h2>Explore the mesh</h2><span className="file-badge">{result.triangleCount.toLocaleString()} triangles</span></div>
              <MeshViewer vertices={current.vertices} faces={result.faces} changedVertices={result.changedVertices} tampered={scenario === 'tampered'} filename={result.filename} />
              <div className="scenario-tabs" role="group" aria-label="Mesh scenario">{[['original', 'Original'], ['transformed', 'Rotated & scaled'], ['tampered', 'Edited demo']].map(([name, label]) => <button key={name} className={`scenario ${scenario === name ? 'active' : ''}`} data-scenario={name} aria-pressed={scenario === name} onClick={() => setScenario(name)}>{label}</button>)}</div>
              <p className="scenario-caption">{explanations[scenario]}</p>
            </article>
            <article className="panel verification-panel" aria-live="polite"><div className="panel-heading"><h2>{scenario === 'original' ? 'Original mesh result' : scenario === 'transformed' ? 'Transformation result' : 'Edited mesh result'}</h2></div><div className="verification-body">
              <div className={`status-banner ${valid ? '' : unavailable ? 'warning' : 'invalid'}`}><div className="status-symbol" aria-hidden="true">{unavailable ? '!' : valid ? '✓' : '×'}</div><div><strong id="status-title">{unavailable ? 'Check could not complete' : valid ? 'Signature verified' : 'Verification failed'}</strong><p>{current.error || (valid ? (scenario === 'transformed' ? 'The fingerprint still matches after this rotation, scale and translation.' : 'The signature is valid for your original mesh.') : matching ? 'The signature is not valid for this fingerprint.' : 'The edited geometry no longer matches the signed fingerprint.')}</p></div></div>
              {scenario === 'tampered' && current.verified === false && <p className="expected-note">✓ This rejection is expected: the demo deliberately changed the mesh.</p>}
              <div className="hash-box"><div><span className="label">Geometry fingerprint</span><button className="text-button" disabled={!current.hash} onClick={async () => {try {await navigator.clipboard.writeText(current.hash); notify('Fingerprint copied.');} catch {notify('Select the fingerprint text to copy it.');}}}>Copy</button></div><p className="hash-help">A hash calculated from the mesh’s vertex geometry.</p><code id="current-hash">{current.hash || 'Not available'}</code><span className={`hash-match ${matching ? '' : 'invalid'}`}>{unavailable ? 'Comparison unavailable' : matching ? '✓ Matches the original' : '× Different from the original'}</span></div>
              {scenario !== 'original' && <details className="hash-details"><summary>Compare with the original fingerprint</summary><code>{result.scenarios.original.hash}</code></details>}
              <div className="detail-row"><span>Signature algorithm</span><strong>ML-DSA-44</strong></div><div className="detail-row"><span>Fingerprint algorithm</span><strong>SHA-256</strong></div>
            </div></article>
          </section>
          <section className="save-panel" aria-labelledby="save-heading"><div className="save-copy"><span className="eyebrow">3 / Keep your result</span><h2 id="save-heading">Save your verification kit</h2><p>One file containing the original mesh’s signature and public key. Keep it with your mesh to verify it later.</p><small>{saved ? '✓ Kit downloaded. Your original mesh file is still needed for verification.' : 'A new signing run creates a new keypair. Save this kit before starting another run.'}</small></div><div className="save-actions"><button className="button primary" onClick={saveKit}>↓ {saved ? 'Download kit again' : 'Save verification kit'}</button><button className="button secondary" onClick={verifyCurrent}>Verify this mesh now →</button></div></section>
          <details className="secondary-downloads"><summary>Separate files and processing report</summary><div className="download-row"><button className="button secondary" onClick={() => download(`${result.filename}.sig.json`, result.sidecar)}>↓ Signature JSON</button><button className="button secondary" onClick={() => download('public.key', publicKeyBytes(result.publicKey), 'application/octet-stream')}>↓ Public key</button><button className="button secondary" onClick={report}>↓ Export report</button></div></details>
          <section className="panel checks-panel" id="checks"><div className="panel-heading"><h2>What did the checks find?</h2><span className="file-badge">5 experiments</span></div><p className="section-intro">An edited mesh, a changed signature, and a wrong key should be rejected. Rejection in these tests is the expected outcome.</p><div className="table-wrap"><table><thead><tr><th>Test</th><th>Expected</th><th>Actual result</th><th>Outcome</th></tr></thead><tbody>{result.checks.map(check => <tr key={check.title}><th scope="row">{check.title}</th><td data-label="Expected">{check.expected ? 'Signature valid' : 'Signature invalid'}</td><td data-label="Actual"><span className={`result-pill ${check.actual ? '' : 'rejected'}`}>{check.actual === null ? 'Not completed' : check.actual ? 'Valid' : 'Invalid'}</span></td><td data-label="Outcome" className={check.actual !== check.expected ? 'unexpected' : 'check-pass'}>{check.actual === null ? 'Could not complete' : check.actual === check.expected ? '✓ As expected' : '△ Needs attention'}{check.error && <small>{check.error}</small>}</td></tr>)}</tbody></table></div><p className="checks-note">The rotation, scaling and translation test runs in memory. A file export and re-import can produce a different result.</p></section>
        </> : <section className="getting-started"><h2>{busy ? 'Your mesh is being processed' : 'What happens after upload?'}</h2><div><article><span>01</span><h3>Create a fingerprint</h3><p>Calculate a geometry hash from the uploaded mesh.</p></article><article><span>02</span><h3>Sign and test it</h3><p>Create a post-quantum signature and run five checks.</p></article><article><span>03</span><h3>Save your verification kit</h3><p>Download the files you need to verify the mesh later.</p></article></div></section>}
        <details className="panel pipeline-panel" id="pipeline"><summary>How the fingerprint and signature are created <span>Technical details</span></summary><div className="pipeline">{[['1', 'Center', 'Remove translation'], ['2', 'Normalize', 'Remove uniform scale'], ['3', 'Align', 'Resolve orientation*'], ['4', 'Quantize & sort', 'Order the representation'], ['5', 'SHA-256', 'Calculate the fingerprint'], ['6', 'ML-DSA-44', 'Sign and verify']].map(([number, title, caption]) => <div className="pipeline-step" key={title}><span>{number}</span><strong>{title}</strong><small>{caption}</small></div>)}</div><p className="pipeline-note">* Symmetric or rank-deficient meshes may use the distance-based fallback.</p>{result && <div className="timing-strip">{Object.entries(result.timings).map(([name, time]) => <span key={name}>{name} <strong>{time.toFixed(1)} ms</strong></span>)}</div>}</details>
      </div>
      <div hidden={view !== 'verify'}><section className="page-heading"><div><div className="eyebrow">Check a signed asset</div><h1>Verify a mesh</h1><p>Check a mesh against a saved signature. You’ll need the mesh and its verification kit.</p></div></section><VerifyForm seed={verifySeed} onGoToSign={() => navigate('sign')} /></div>
      <footer className="page-footer"><span>postquantum3D · B.Tech Project 1</span><span>Checks vertex geometry. Textures and materials are not included.</span></footer>
    </main>
    {notification && <div className="toast" role="status">{notification}</div>}
  </>;
}
