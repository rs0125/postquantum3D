import React, { useEffect, useRef, useState } from 'react';

const vertexShader = `
attribute vec3 position;
attribute vec3 normal;
attribute vec3 color;
uniform float yaw;
uniform float pitch;
uniform float zoom;
uniform float aspect;
uniform float zUp;
varying vec3 shade;
vec3 orient(vec3 p) {
  if (zUp > 0.5) p = vec3(p.x, p.z, -p.y);
  p = vec3(p.x*cos(yaw)+p.z*sin(yaw), p.y, -p.x*sin(yaw)+p.z*cos(yaw));
  return vec3(p.x, p.y*cos(pitch)-p.z*sin(pitch), p.y*sin(pitch)+p.z*cos(pitch));
}
void main() {
  vec3 p = orient(position) * zoom;
  p.z -= 4.3;
  gl_Position = vec4(p.x*2.7/aspect, p.y*2.7-0.14*p.z, -1.002*p.z-0.2002, -p.z);
  float light = 0.32 + 0.68 * max(0.0, dot(normalize(orient(normal)), normalize(vec3(-0.4,0.7,1.0))));
  shade = color * light;
}`;
const fragmentShader = `precision mediump float; varying vec3 shade; void main(){ gl_FragColor=vec4(shade,1.0); }`;

export default function MeshViewer({ vertices, faces, changedVertices, tampered, filename }) {
  const canvasRef = useRef(null);
  const renderer = useRef(null);
  const [wireframe, setWireframe] = useState(false);
  const [zUp, setZUp] = useState(false);
  const [error, setError] = useState('');
  const [contextVersion, setContextVersion] = useState(0);

  useEffect(() => {
    if (!vertices?.length || !faces?.length) return;
    const canvas = canvasRef.current;
    const gl = canvas.getContext('webgl', { alpha: true, antialias: true, preserveDrawingBuffer: true });
    if (!gl) { setError('Enable WebGL in your browser to display the 3D preview. Processing results are still available.'); return; }
    setError('');
    const shaders = [];
    let program, buffer;
    const cleanupGL = () => {
      if (buffer) gl.deleteBuffer(buffer);
      if (program) gl.deleteProgram(program);
      shaders.forEach(shader => gl.deleteShader(shader));
    };
    try {
      program = gl.createProgram();
      for (const [kind, source] of [[gl.VERTEX_SHADER, vertexShader], [gl.FRAGMENT_SHADER, fragmentShader]]) {
        const shader = gl.createShader(kind);
        shaders.push(shader);
        gl.shaderSource(shader, source); gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
        gl.attachShader(program, shader);
      }
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Could not initialize the 3D renderer.');
      gl.useProgram(program);
      const changed = new Set(tampered ? changedVertices : []);
      const floats = new Float32Array(faces.length * 3 * 9);
      let offset = 0;
      for (const face of faces) {
        const [a, b, c] = face.map(index => vertices[index]);
        const u = b.map((value, i) => value - a[i]), v = c.map((value, i) => value - a[i]);
        const normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
        const length = Math.hypot(...normal) || 1;
        const color = face.some(index => changed.has(index)) ? [1, 0.43, 0.36] : [0.73, 0.89, 0.51];
        for (const point of [a, b, c]) {
          floats.set([...point, ...normal.map(value => value / length), ...color], offset);
          offset += 9;
        }
      }
      buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.bufferData(gl.ARRAY_BUFFER, floats, gl.STATIC_DRAW);
      for (const [name, start] of [['position', 0], ['normal', 12], ['color', 24]]) {
        const location = gl.getAttribLocation(program, name);
        gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 36, start);
      }
      const uniforms = Object.fromEntries(['yaw', 'pitch', 'zoom', 'aspect', 'zUp'].map(name => [name, gl.getUniformLocation(program, name)]));
      const state = { yaw: -0.35, pitch: -0.12, zoom: 1, wireframe: false, zUp: false };
      let frame;
      function draw() {
        frame = null;
        const dpr = Math.min(devicePixelRatio || 1, 2);
        canvas.width = Math.round(canvas.clientWidth * dpr);
        canvas.height = Math.round(canvas.clientHeight * dpr);
        if (!canvas.width || !canvas.height) return;
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.enable(gl.DEPTH_TEST); gl.useProgram(program);
        for (const [name, location] of Object.entries(uniforms)) gl.uniform1f(location, name === 'aspect' ? canvas.width / canvas.height : Number(state[name]));
        if (state.wireframe) {
          // Bound draw calls for large meshes while keeping all vertices available.
          const stride = Math.max(1, Math.ceil(faces.length / 8000));
          for (let i = 0; i < faces.length; i += stride) gl.drawArrays(gl.LINE_LOOP, i * 3, 3);
        } else gl.drawArrays(gl.TRIANGLES, 0, faces.length * 3);
      }
      const requestDraw = () => { if (frame == null) frame = requestAnimationFrame(draw); };
      renderer.current = { state, requestDraw };
      let drag;
      const down = event => { drag = [event.clientX, event.clientY]; canvas.setPointerCapture(event.pointerId); };
      const move = event => {
        if (!drag) return;
        state.yaw += (event.clientX - drag[0]) * 0.009;
        state.pitch = Math.max(-1.4, Math.min(1.4, state.pitch + (event.clientY - drag[1]) * 0.009));
        drag = [event.clientX, event.clientY]; requestDraw();
      };
      const up = () => { drag = null; };
      const wheel = event => { event.preventDefault(); state.zoom = Math.max(0.45, Math.min(2.3, state.zoom * Math.exp(-event.deltaY * 0.001))); requestDraw(); };
      const key = event => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-', '0'].includes(event.key)) return;
        event.preventDefault();
        if (event.key === 'ArrowLeft') state.yaw -= 0.1;
        if (event.key === 'ArrowRight') state.yaw += 0.1;
        if (event.key === 'ArrowUp') state.pitch -= 0.1;
        if (event.key === 'ArrowDown') state.pitch += 0.1;
        if (['+', '='].includes(event.key)) state.zoom = Math.min(2.3, state.zoom + 0.1);
        if (event.key === '-') state.zoom = Math.max(0.45, state.zoom - 0.1);
        if (event.key === '0') Object.assign(state, {yaw: -0.35, pitch: -0.12, zoom: 1});
        requestDraw();
      };
      const lost = event => { event.preventDefault(); setError('3D context lost. Waiting for the browser to restore it…'); };
      const restored = () => setContextVersion(value => value + 1);
      const events = {pointerdown: down, pointermove: move, pointerup: up, pointercancel: up, lostpointercapture: up, wheel, keydown: key, webglcontextlost: lost, webglcontextrestored: restored};
      Object.entries(events).forEach(([name, fn]) => canvas.addEventListener(name, fn, {passive: false}));
      const observer = new ResizeObserver(requestDraw); observer.observe(canvas); requestDraw();
      return () => {
        observer.disconnect(); cancelAnimationFrame(frame);
        Object.entries(events).forEach(([name, fn]) => canvas.removeEventListener(name, fn));
        renderer.current = null; cleanupGL();
      };
    } catch (failure) { cleanupGL(); setError(`3D preview unavailable: ${failure.message}`); }
  }, [vertices, faces, changedVertices, tampered, contextVersion]);

  useEffect(() => {
    if (!renderer.current) return;
    Object.assign(renderer.current.state, {wireframe, zUp});
    renderer.current.requestDraw();
  }, [wireframe, zUp, vertices, faces, contextVersion]);

  const reset = () => {
    if (!renderer.current) return;
    Object.assign(renderer.current.state, {yaw: -0.35, pitch: -0.12, zoom: 1});
    renderer.current.requestDraw();
  };
  const zoomView = delta => {
    if (!renderer.current) return;
    renderer.current.state.zoom = Math.max(0.45, Math.min(2.3, renderer.current.state.zoom + delta));
    renderer.current.requestDraw();
  };

  return <div className="viewport">
    <div className="viewport-top"><span className="viewport-label" title={filename}>{filename}</span><span className="viewport-mode">3D preview</span></div>
    <div className="stage-grid" />
    <canvas id="mesh-canvas" ref={canvasRef} tabIndex={0} role="img" aria-label="3D mesh. Drag or use arrow keys to rotate. Scroll or use plus and minus to zoom." />
    {error && <div className="viewer-error" role="status">{error}</div>}
    <div className="viewer-tools"><button className="icon-button" aria-label="Toggle wireframe" aria-pressed={wireframe} onClick={() => setWireframe(!wireframe)}>▧ Wireframe</button><button className="icon-button" aria-label="Reset camera" onClick={reset}>↺ Reset view</button><button className="icon-button up-axis" title="Change which axis points up" aria-label="Switch vertical axis" onClick={() => setZUp(!zUp)}>{zUp ? 'Z up' : 'Y up'} ↕</button><span className="zoom-controls"><button className="icon-button" aria-label="Zoom out" onClick={() => zoomView(-0.15)}>−</button><button className="icon-button" aria-label="Zoom in" onClick={() => zoomView(0.15)}>+</button></span></div>
    <div className="viewport-bottom"><span>{wireframe && faces.length > 8000 ? 'Wireframe displays sampled triangles' : 'Drag to rotate · Use + / − to zoom'}</span></div>
  </div>;
}
