// Pad page — path-tracer tab (three-gpu-pathtracer scaffold).
//
// Boots lazily on first activation of the Path-tracer tab. All ES module
// imports run via dynamic import() so that any load/version failure is
// reported in the status line instead of dying silently at parse time.
//
// First iteration: placeholder scene (a cube on a ground plane plus a
// ring of 24 emissive cubes, mirroring render_rainbow_ring.py's hue
// sweep). Verifies that:
//   - three + three-gpu-pathtracer load via esm.sh,
//   - GPU path tracer initialises against #pad-pt-canvas,
//   - sample accumulation runs in rAF and reports `samples` to the UI,
//   - iris (f-stop) drives the thin-lens camera, ISO drives a temporary
//     exposure stand-in.

const tabButton = document.getElementById('pad-tab-pathtracer');
const canvas    = document.getElementById('pad-pt-canvas');
const samplesEl = document.getElementById('pad-pt-samples');
const statusEl  = document.getElementById('pad-pt-status');
const fallback  = document.getElementById('pad-pt-fallback');

let booted = false;
let runtime = null;

function setStatus(text, cls) {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.classList.remove('error', 'ready');
  if (cls) statusEl.classList.add(cls);
  // Mirror to console so we can correlate with network panel.
  console.log('[pad-pt]', text);
}

async function bootIfNeeded() {
  if (booted) return;
  booted = true;

  if (!canvas) {
    setStatus('canvas missing', 'error');
    return;
  }
  // Don't probe getContext() ourselves — once a canvas has any context
  // bound, THREE.WebGLRenderer's own getContext() call returns null and
  // we crash with "Cannot read properties of null (reading 'precision')".
  // If WebGL2 is unavailable, the renderer construction below throws and
  // the catch in this function surfaces it in the status line.

  setStatus('loading three.js…');
  let THREE, PT;
  try {
    THREE = await import('https://esm.sh/three@0.165.0');
  } catch (err) {
    console.error(err);
    setStatus(`three load failed: ${err.message || err}`, 'error');
    return;
  }

  setStatus('loading path tracer…');
  try {
    PT = await import('https://esm.sh/three-gpu-pathtracer@0.0.23?deps=three@0.165.0,three-mesh-bvh@0.7.4');
  } catch (err) {
    console.error(err);
    setStatus(`pathtracer load failed: ${err.message || err}`, 'error');
    return;
  }

  setStatus('loading GLTFLoader…');
  let GLTFLoader;
  try {
    const mod = await import('https://esm.sh/three@0.165.0/examples/jsm/loaders/GLTFLoader.js');
    GLTFLoader = mod.GLTFLoader;
  } catch (err) {
    console.error(err);
    setStatus(`gltf loader failed: ${err.message || err}`, 'error');
    return;
  }

  setStatus('loading scene .glb…');
  let gltf;
  try {
    const loader = new GLTFLoader();
    gltf = await loader.loadAsync('/static/scenes/rainbow_ring.glb');
  } catch (err) {
    console.error(err);
    setStatus(`scene load failed: ${err.message || err}`, 'error');
    return;
  }

  setStatus('initialising scene…');
  try {
    runtime = boot(canvas, THREE, PT, gltf);
    setStatus('rendering', 'ready');
  } catch (err) {
    console.error(err);
    setStatus(`init failed: ${err.message || err}`, 'error');
  }
}

if (tabButton) {
  tabButton.addEventListener('shown.bs.tab', bootIfNeeded);
} else {
  // No tab button — boot immediately (atlas/test contexts).
  bootIfNeeded();
}

// ---------------------------------------------------------------------------
// Pad-control input plumbing — read the same hidden inputs pad.js owns.
// ---------------------------------------------------------------------------

const IRIS_FSTOPS  = [1.4, 2.0, 2.8, 4.0, 5.6, 8.0, 11.0, 16.0, 22.0];
const SHUTTER_SECS = [1/4000, 1/1000, 1/500, 1/250, 1/125, 1/60, 1/30, 1/8, 1.0, 4.0];
const ISO_VALUES   = [100, 200, 400, 800, 1600, 3200, 6400];

function lerpIndex(arr, fval) {
  if (!arr.length) return 0;
  const c = Math.max(0, Math.min(arr.length - 1, fval));
  const lo = Math.floor(c), hi = Math.min(arr.length - 1, Math.ceil(c));
  return arr[lo] + (arr[hi] - arr[lo]) * (c - lo);
}
function logLerpIndex(arr, fval) {
  const c = Math.max(0, Math.min(arr.length - 1, fval));
  const lo = Math.floor(c), hi = Math.min(arr.length - 1, Math.ceil(c));
  const frac = c - lo;
  return Math.exp(Math.log(arr[lo]) + frac * (Math.log(arr[hi]) - Math.log(arr[lo])));
}

function readInputs() {
  const iris    = document.getElementById('pad-iris-input');
  const shutter = document.getElementById('pad-shutter-input');
  const iso     = document.getElementById('pad-iso-input');
  return {
    fstop:     iris    ? lerpIndex(IRIS_FSTOPS, +iris.value)        : 4.0,
    shutter_s: shutter ? logLerpIndex(SHUTTER_SECS, +shutter.value) : 1/125,
    iso:       iso     ? Math.round(logLerpIndex(ISO_VALUES, +iso.value)) : 400,
  };
}

// ---------------------------------------------------------------------------
// Boot routine — builds the renderer, scene, and accumulation loop.
// THREE and PT modules are passed in so we can dynamic-import them.
// ---------------------------------------------------------------------------

function boot(canvasEl, THREE, PT, gltf) {
  const { WebGLPathTracer, PhysicalCamera } = PT;
  if (!WebGLPathTracer) throw new Error('WebGLPathTracer export missing');

  const renderer = new THREE.WebGLRenderer({
    canvas: canvasEl,
    antialias: false,
    alpha: false,
  });
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;

  const pathTracer = new WebGLPathTracer(renderer);
  pathTracer.minSamples = 1;
  pathTracer.renderDelay = 0;
  pathTracer.fadeDuration = 0;
  pathTracer.renderScale = 0.5;     // half-res accumulator, faster iteration

  // Use the Blender-exported scene as-is. The exporter packs cameras
  // and lights as scene children — pull out the first PerspectiveCamera
  // we find so framing matches the .blend.
  const scene = gltf.scene;
  scene.background = new THREE.Color(0x000000);

  let blenderCam = null;
  scene.traverse((obj) => {
    if (!blenderCam && obj.isCamera && obj.isPerspectiveCamera) {
      blenderCam = obj;
    }
  });

  // PhysicalCamera (PT) extends PerspectiveCamera with fStop /
  // apertureBlades / focusDistance. If we've got a Blender camera,
  // mirror its pose + intrinsics into a PhysicalCamera so the path
  // tracer's thin-lens model can use them.
  const Cam = PhysicalCamera || THREE.PerspectiveCamera;
  const camera = new Cam();
  if (blenderCam) {
    camera.position.copy(blenderCam.getWorldPosition(new THREE.Vector3()));
    camera.quaternion.copy(blenderCam.getWorldQuaternion(new THREE.Quaternion()));
    camera.fov  = blenderCam.fov;
    camera.near = blenderCam.near;
    camera.far  = blenderCam.far;
    camera.updateProjectionMatrix();
    console.log('[pad-pt] using Blender camera', {
      pos: camera.position.toArray(), fov: camera.fov,
    });
  } else {
    // Sensible default if no camera was exported.
    camera.fov = 35; camera.near = 0.1; camera.far = 2000;
    camera.position.set(0, 1.2, 6);
    camera.lookAt(0, 0.5, 0);
    camera.updateProjectionMatrix();
  }
  if ('focusDistance'   in camera) camera.focusDistance   = camera.position.length();
  if ('fStop'           in camera) camera.fStop           = 4.0;
  if ('apertureBlades'  in camera) camera.apertureBlades  = 6;

  // Find the ring pivot so we can animate it. render_rainbow_ring.py
  // names it "RainbowRingPivot"; if absent, fall back to spinning
  // every node whose name starts with "RainbowCube_".
  let ringPivot = null;
  const ringCubes = [];
  scene.traverse((obj) => {
    if (obj.name === 'RainbowRingPivot') ringPivot = obj;
    if (obj.name.startsWith('RainbowCube_')) ringCubes.push(obj);
  });
  console.log('[pad-pt] ring pivot found:', !!ringPivot, 'cubes:', ringCubes.length);

  pathTracer.setScene(scene, camera);
  applyControls(pathTracer, camera, renderer);

  const inputs = ['pad-iris-input', 'pad-shutter-input', 'pad-iso-input']
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  const onInputChange = () => applyControls(pathTracer, camera, renderer);
  inputs.forEach((el) => el.addEventListener('input', onInputChange));

  // ---- animation + shutter wiring ----
  // The ring spins at a constant angular speed in wall-clock time.
  // Each rAF tick advances rotation by `dt`, then we either:
  //  (a) keep accumulating into the current exposure (samples build up
  //      across a small rotation slice — that *is* the motion blur), or
  //  (b) close the exposure once the configured shutter window has
  //      elapsed in wall-clock seconds, and reset to start the next one.
  // setScene() per tick rebuilds BVH; for ~few-thousand-tri scenes it's
  // fast enough. If it gets sluggish we'll cap the per-tick rebuild.
  const SPIN_RAD_PER_S = (2 * Math.PI) / 6.0;   // one revolution in 6 s
  let lastWallTime = performance.now() / 1000;
  let exposureTime = 0;
  let stopped = false;
  function tick() {
    if (stopped) return;
    const now = performance.now() / 1000;
    const dt = Math.min(now - lastWallTime, 0.05);  // clamp huge tab-sleep gaps
    lastWallTime = now;

    // Spin the ring (object-space rotation around its parent's Y axis,
    // matching Blender's pivot setup).
    if (ringPivot) {
      ringPivot.rotation.y += SPIN_RAD_PER_S * dt;
    } else {
      // Fallback: revolve each cube around scene origin's Y axis.
      const dTheta = SPIN_RAD_PER_S * dt;
      const c = Math.cos(dTheta), s = Math.sin(dTheta);
      ringCubes.forEach((cube) => {
        const x = cube.position.x, z = cube.position.z;
        cube.position.x = c * x - s * z;
        cube.position.z = s * x + c * z;
      });
    }

    // Refresh BVH against the new transforms, then add a sample.
    pathTracer.setScene(scene, camera);
    pathTracer.renderSample();

    // Close the exposure once the user-selected shutter window elapses.
    const shutter_s = readInputs().shutter_s;
    exposureTime += dt;
    if (exposureTime >= shutter_s) {
      pathTracer.reset();
      exposureTime = 0;
    }

    if (samplesEl) samplesEl.textContent = String(pathTracer.samples | 0);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  return {
    renderer, pathTracer, scene, camera, ringPivot, ringCubes,
    dispose() {
      stopped = true;
      inputs.forEach((el) => el.removeEventListener('input', onInputChange));
      pathTracer.dispose?.();
      renderer.dispose();
    },
  };
}

// ---------------------------------------------------------------------------
// Iris → camera fStop. ISO → temporary exposure stand-in (real noise
// pass lands later). Shutter wiring is deferred — needs per-sample
// scene-time advance for motion blur.
// ---------------------------------------------------------------------------

function applyControls(pathTracer, camera, renderer) {
  const ctl = readInputs();
  if ('fStop' in camera && camera.fStop !== ctl.fstop) {
    camera.fStop = ctl.fstop;
    if (camera.updateProjectionMatrix) camera.updateProjectionMatrix();
    if (pathTracer.updateCamera) pathTracer.updateCamera();
    if (pathTracer.reset) pathTracer.reset();
  }
  const isoStops = Math.log2(ctl.iso / 400);
  renderer.toneMappingExposure = Math.pow(2, isoStops * 0.5);
}
