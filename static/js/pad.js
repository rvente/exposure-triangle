/* Virtual camera — G4 item #11 (restore spec, 2026-04-24).

   Two render surfaces driven by the same procedural WebGL2 scene:

     - #pad-live-canvas  (small, e.g. 384²): always-on viewfinder.
       Renders fresh every frame at LIVE_SHUTTER_S = 1/120 s with
       INTERACTIVE_SPP samples so iris + ISO scrubbing stays responsive.

     - #pad-photo-canvas (larger, e.g. 1024²): photograph surface.
       Starts empty; on Snap, accumulates TARGET_SPP samples at the
       user's chosen shutter value. When the exposure finishes, the
       frame is read via canvas.toDataURL() and pushed to the album.

   Each canvas gets its own WebGL2 context + program/FBO pair. Shader
   source is shared; compilation is per-context. This is simpler than
   round-tripping via readPixels+putImageData, and the per-frame cost
   is dominated by the sample loop in the fragment shader, not by
   having two programs resident.

   Scene (analytic, evaluated inside the fragment shader):
     - Foreground: two matte Lambertian cubes on the floor plane, each
       spinning about its own local Y axis.
     - Background: five emissive "light" cubes at distance — bokeh +
       motion-trail sources. Their slow lateral drift + vertical bob
       integrates into visible streaks at long shutter windows.
     - Floor: checkerboard matte.

   Per pixel, per frame: N ray samples, each jittered across the
   aperture disk (DoF) and along the shutter window (motion blur).
   ISO is applied as a post-process Poisson-Gaussian noise term.

   The snap path is structured as an internal renderSnapHDR shape so a
   future neural HDR renderer (roadmap item #13, Stage 4 stretch) can
   swap in without touching the preview / album / noise surfaces. No
   explicit interface is defined — the private shape is the contract. */

(function () {
  'use strict';

  // ---------- tunables ----------
  const INTERACTIVE_SPP   = 16;      // live viewfinder samples per frame
  const SNAP_PER_FRAME    = 64;      // samples added per snap-mode frame
  const SNAP_MIN_SPP      = 1024;    // floor for fastest shutters
  const SNAP_MAX_SPP      = 16384;   // ceiling for longest shutters
  const SNAP_BASE_SPP     = 256;     // baseline multiplier
  const LIVE_SHUTTER_S    = 1.0 / 120.0;

  // ---------- vertex shader (fullscreen triangle) ----------
  const VS_SRC = `#version 300 es
    precision highp float;
    out vec2 v_uv;
    void main() {
      vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
      v_uv = p;
      gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
    }
  `;

  // ---------- fragment shader (scene + DoF + motion blur + noise) ----------
  const FS_SCENE_SRC = `#version 300 es
    precision highp float;

    uniform vec2  u_resolution;
    uniform float u_fstop;      // f-number [1.4, 22]
    uniform float u_shutter;    // shutter window in seconds
    uniform float u_iso;        // [100, 6400]
    uniform float u_time;       // seconds, scene animation clock
    uniform float u_seed;       // per-frame noise re-seed
    uniform int   u_samples;    // spp this pass
    uniform int   u_sample_offset; // Halton index offset

    in vec2 v_uv;
    out vec4 fragColor;

    // ---- Halton low-discrepancy sequence for stratified-ish sampling ----
    float halton(int index, int base) {
      float f = 1.0;
      float r = 0.0;
      int i = index;
      for (int k = 0; k < 32; k++) {
        if (i <= 0) break;
        f /= float(base);
        r += f * float(i - (i / base) * base);
        i /= base;
      }
      return r;
    }

    vec2 concentricDisk(vec2 u) {
      vec2 s = u * 2.0 - 1.0;
      if (abs(s.x) < 1e-6 && abs(s.y) < 1e-6) return vec2(0.0);
      float r, theta;
      if (abs(s.x) > abs(s.y)) {
        r = s.x;
        theta = 0.7853981634 * (s.y / s.x);
      } else {
        r = s.y;
        theta = 1.5707963268 - 0.7853981634 * (s.x / s.y);
      }
      return r * vec2(cos(theta), sin(theta));
    }

    // ---- scene primitives ----
    const float FLOOR_Y  = -1.1;
    const int   N_FG     = 2;
    const int   N_BG     = 5;
    const float FG_HALF  = 0.28;
    const float BG_HALF  = 0.22;

    vec3 fgCenter(int i) {
      if (i == 0) return vec3(-0.75, FLOOR_Y + FG_HALF, -0.8);
      return           vec3(+0.85, FLOOR_Y + FG_HALF, -1.2);
    }
    float fgSpin(int i) {
      if (i == 0) return 1.5;
      return 1.2;
    }
    vec3 fgAlbedo(int i) {
      if (i == 0) return vec3(0.72, 0.70, 0.66);
      return           vec3(0.64, 0.58, 0.52);
    }

    vec3 bgCenter(int i, float t) {
      // Slow lateral drift along X + tiny vertical bob. At 1/120 s the
      // drift is invisible; at 1 s it integrates into visible streaks.
      float drift = sin(t * 0.35 + float(i) * 1.7) * 0.4;
      vec3 base;
      if      (i == 0) base = vec3(-3.5, 0.4, -6.0);
      else if (i == 1) base = vec3(-1.4, 0.9, -7.5);
      else if (i == 2) base = vec3( 0.5, 1.2, -8.0);
      else if (i == 3) base = vec3( 2.3, 0.7, -7.2);
      else             base = vec3( 3.8, 0.3, -5.8);
      return base + vec3(drift, sin(t * 0.6 + float(i)) * 0.1, 0.0);
    }
    vec3 bgEmissive(int i) {
      if (i == 0) return vec3(5.4, 3.6, 1.8);
      if (i == 1) return vec3(2.0, 4.8, 5.4);
      if (i == 2) return vec3(5.6, 2.2, 4.6);
      if (i == 3) return vec3(4.8, 4.6, 1.2);
      return           vec3(1.6, 5.2, 3.6);
    }

    vec3 rotY(vec3 v, float a) {
      float c = cos(a), s = sin(a);
      return vec3(c * v.x + s * v.z, v.y, -s * v.x + c * v.z);
    }

    // Ray-AABB (slab method).
    float iBox(vec3 ro, vec3 rd, vec3 cmin, vec3 cmax, out vec3 nrm) {
      vec3 inv = 1.0 / rd;
      vec3 t0s = (cmin - ro) * inv;
      vec3 t1s = (cmax - ro) * inv;
      vec3 tmin = min(t0s, t1s);
      vec3 tmax = max(t0s, t1s);
      float tN = max(max(tmin.x, tmin.y), tmin.z);
      float tF = min(min(tmax.x, tmax.y), tmax.z);
      if (tN > tF || tF < 1e-3) { nrm = vec3(0); return -1.0; }
      float t = tN > 1e-3 ? tN : tF;
      vec3 p = ro + rd * t;
      vec3 centered = p - 0.5 * (cmin + cmax);
      vec3 d = abs(centered) / (0.5 * (cmax - cmin));
      if (d.x > d.y && d.x > d.z)      nrm = vec3(sign(centered.x), 0, 0);
      else if (d.y > d.z)              nrm = vec3(0, sign(centered.y), 0);
      else                             nrm = vec3(0, 0, sign(centered.z));
      return t;
    }

    float iPlaneY(vec3 ro, vec3 rd, float y) {
      if (abs(rd.y) < 1e-6) return -1.0;
      float t = (y - ro.y) / rd.y;
      return t > 1e-3 ? t : -1.0;
    }

    vec3 sky(vec3 rd) {
      float h = clamp(rd.y * 0.5 + 0.5, 0.0, 1.0);
      return mix(vec3(0.01, 0.01, 0.02), vec3(0.04, 0.05, 0.08), h);
    }

    vec3 cubeLight(vec3 p, vec3 n, float t) {
      vec3 lit = vec3(0.0);
      for (int i = 0; i < N_BG; i++) {
        vec3 c = bgCenter(i, t);
        vec3 L = c - p;
        float d2 = max(dot(L, L), 0.5);
        vec3 Ldir = L / sqrt(d2);
        float nd = max(dot(n, Ldir), 0.0);
        lit += bgEmissive(i) * nd / d2;
      }
      return lit;
    }

    float iSpinCube(vec3 ro, vec3 rd, int i, float t, out vec3 nrm) {
      vec3 c = fgCenter(i);
      float a = t * fgSpin(i) + float(i) * 1.3;
      vec3 roL = rotY(ro - c, -a);
      vec3 rdL = rotY(rd, -a);
      vec3 nL;
      float tHit = iBox(roL, rdL, vec3(-FG_HALF), vec3(FG_HALF), nL);
      if (tHit < 0.0) { nrm = vec3(0); return -1.0; }
      nrm = rotY(nL, a);
      return tHit;
    }

    vec3 trace(vec3 ro, vec3 rd, float t) {
      float tBest = 1e9;
      int hit = -1;
      vec3 nBest = vec3(0.0);

      float tp = iPlaneY(ro, rd, FLOOR_Y);
      if (tp > 0.0 && tp < tBest) { tBest = tp; hit = 0; }

      for (int i = 0; i < N_FG; i++) {
        vec3 n;
        float tc = iSpinCube(ro, rd, i, t, n);
        if (tc > 0.0 && tc < tBest) { tBest = tc; hit = 1 + i; nBest = n; }
      }

      for (int i = 0; i < N_BG; i++) {
        vec3 c = bgCenter(i, t);
        vec3 n;
        float tc = iBox(ro, rd, c - vec3(BG_HALF), c + vec3(BG_HALF), n);
        if (tc > 0.0 && tc < tBest) { tBest = tc; hit = 10 + i; nBest = n; }
      }

      if (hit < 0) return sky(rd);

      vec3 p = ro + rd * tBest;
      vec3 ambient = vec3(0.05);
      vec3 sun = normalize(vec3(0.6, 0.9, -0.3));
      vec3 sunColor = vec3(1.2, 1.1, 0.95);

      if (hit == 0) {
        vec3 n = vec3(0.0, 1.0, 0.0);
        float sq = step(fract(p.x * 0.5) + fract(p.z * 0.5), 0.999) *
                   step(0.5, fract(p.x * 0.5 + p.z * 0.5));
        vec3 albedo = mix(vec3(0.12), vec3(0.22), sq);
        float sunTerm = max(dot(n, sun), 0.0);
        return albedo * (ambient + sunColor * sunTerm + cubeLight(p, n, t));
      } else if (hit <= N_FG) {
        int ci = hit - 1;
        vec3 albedo = fgAlbedo(ci);
        float sunTerm = max(dot(nBest, sun), 0.0);
        return albedo * (ambient + sunColor * sunTerm + cubeLight(p, nBest, t));
      } else {
        int bi = hit - 10;
        return bgEmissive(bi);
      }
    }

    vec3 addSensorNoise(vec3 clean, float iso, vec2 uv, float seed) {
      float gain = iso / 100.0;
      vec3 rand = fract(sin(vec3(
          dot(uv, vec2(12.9898, 78.233)) + seed,
          dot(uv, vec2(93.9898, 67.345)) + seed,
          dot(uv, vec2(43.332, 93.532)) + seed
        )) * 43758.5453);
      vec3 g = sqrt(-2.0 * log(max(rand, vec3(1e-6)))) * cos(6.2831853 * rand.yzx);
      float read_noise = 0.005;
      vec3 noise = sqrt(max(clean, vec3(0.0)) * gain) * g / max(gain, 1e-4)
                 + read_noise * sqrt(gain) * g.yzx;
      return max(clean + noise, vec3(0.0));
    }

    void main() {
      vec2 uv = v_uv;
      vec2 ndc = uv * 2.0 - 1.0;
      ndc.x *= u_resolution.x / u_resolution.y;

      float focalLen  = 1.4;
      float focalDist = 2.5;
      float apertureR = 0.5 * focalLen / max(u_fstop, 0.5);

      vec3 camPos = vec3(0.0, 0.6, -2.6);
      vec3 target = vec3(0.0, -0.4, 0.0);
      vec3 fwd = normalize(target - camPos);
      vec3 right = normalize(cross(fwd, vec3(0.0, 1.0, 0.0)));
      vec3 up = cross(right, fwd);

      vec3 pixelOnFocal = camPos + fwd * focalDist
                                 + right * ndc.x * focalDist / focalLen
                                 + up    * ndc.y * focalDist / focalLen;

      vec3 acc = vec3(0.0);
      int N = u_samples;
      for (int s = 0; s < 512; s++) {
        if (s >= N) break;
        int hIdx = s + u_sample_offset + 1;
        float h2 = halton(hIdx, 2);
        float h3 = halton(hIdx, 3);
        float h5 = halton(hIdx, 5);

        vec2 lens = concentricDisk(vec2(h2, h3)) * apertureR;
        vec3 ro = camPos + right * lens.x + up * lens.y;
        vec3 rd = normalize(pixelOnFocal - ro);

        float tSample = u_time + u_shutter * (h5 - 0.5);
        acc += trace(ro, rd, tSample);
      }

      // Write unnormalized sum. Display shader divides by total samples.
      // Noise operates on mean (single-sample scale), then rescaled back
      // so additive accumulation stays valid.
      vec3 mean = acc / float(N);
      vec3 noisy = addSensorNoise(mean, u_iso, uv, u_seed);
      acc = noisy * float(N);

      fragColor = vec4(acc, 1.0);
    }
  `;

  // ---------- display shader (accum FBO → canvas, with tonemap) ----------
  const FS_DISPLAY_SRC = `#version 300 es
    precision highp float;
    uniform sampler2D u_accum;
    uniform float u_inv_samples;
    in vec2 v_uv;
    out vec4 fragColor;
    void main() {
      vec3 hdr = texture(u_accum, v_uv).rgb * u_inv_samples;
      vec3 mapped = hdr / (1.0 + hdr);
      mapped = pow(mapped, vec3(1.0 / 2.2));
      fragColor = vec4(mapped, 1.0);
    }
  `;

  // ---------- shader helpers ----------
  function compileShader(gl, type, src) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(sh);
      console.error('Shader compile error:', log, '\nSource:\n', src);
      gl.deleteShader(sh);
      throw new Error('Shader compile failed: ' + log);
    }
    return sh;
  }

  function linkProgram(gl, vsSrc, fsSrc) {
    const vs = compileShader(gl, gl.VERTEX_SHADER, vsSrc);
    const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSrc);
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      const log = gl.getProgramInfoLog(prog);
      throw new Error('Program link failed: ' + log);
    }
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    return prog;
  }

  function createFBO(gl, w, h) {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, w, h, 0, gl.RGBA, gl.HALF_FLOAT, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    if (status !== gl.FRAMEBUFFER_COMPLETE) {
      throw new Error('Framebuffer incomplete: 0x' + status.toString(16));
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { fbo, tex };
  }

  // ---------- physical-value tables (shared by both surfaces) ----------
  const IRIS_FSTOPS  = [1.4, 2.0, 2.8, 4.0, 5.6, 8.0, 11.0, 16.0, 22.0];
  const SHUTTER_SECS = [1/4000, 1/1000, 1/500, 1/250, 1/125, 1/60, 1/30, 1/8, 1.0, 4.0];
  const ISO_VALUES   = [100, 200, 400, 800, 1600, 3200, 6400];

  function lerpIndex(arr, fval) {
    if (!arr.length) return 0;
    const clamped = Math.max(0, Math.min(arr.length - 1, fval));
    const lo = Math.floor(clamped);
    const hi = Math.min(arr.length - 1, Math.ceil(clamped));
    const frac = clamped - lo;
    return arr[lo] + (arr[hi] - arr[lo]) * frac;
  }
  function logLerpIndex(arr, fval) {
    const clamped = Math.max(0, Math.min(arr.length - 1, fval));
    const lo = Math.floor(clamped);
    const hi = Math.min(arr.length - 1, Math.ceil(clamped));
    const frac = clamped - lo;
    return Math.exp(Math.log(arr[lo]) + frac * (Math.log(arr[hi]) - Math.log(arr[lo])));
  }

  function formatFstop(f)          { return f < 4 ? f.toFixed(1) : f.toFixed(0); }
  function formatShutterReadout(s) { return s >= 1 ? s.toFixed(1) : String(Math.round(1 / s)); }

  // Target sample count for a given shutter duration. Linear in shutter
  // seconds relative to the live shutter, clamped to [MIN, MAX]. Fast
  // shutters finish near-instantly; long shutters take real time to
  // develop — which is the simulation of *taking* the picture.
  //
  // URL param ?snap_min=N lowers the floor so headless e2e runs can
  // complete a snap in seconds rather than minutes under software WebGL.
  function readSnapMinOverride() {
    const v = new URLSearchParams(window.location.search).get('snap_min');
    const n = v ? parseInt(v, 10) : NaN;
    return Number.isFinite(n) && n > 0 ? Math.min(SNAP_MIN_SPP, Math.max(64, n)) : SNAP_MIN_SPP;
  }
  function targetSppForShutter(shutter_s, floor) {
    const raw = SNAP_BASE_SPP * shutter_s / LIVE_SHUTTER_S;
    return Math.max(floor, Math.min(SNAP_MAX_SPP, Math.round(raw)));
  }

  // ---------- per-canvas renderer ----------
  // Encapsulates a WebGL2 context + compiled programs + accumulation FBO
  // for one canvas. Both live and photo surfaces share this factory.
  //
  // Private shape (deliberately unexposed as an interface — see header):
  //   renderSnapHDR(iris, shutter_s, iso, t, resolution) → HDR accumulates
  // is realized by `accumulate({ sceneTime, shutter, samples })`. A future
  // neural HDR renderer (#13) would replace the scene-pass program while
  // keeping accumulation + display + the hosting renderer factory intact.
  function createRenderer(canvas) {
    const gl = canvas.getContext('webgl2', {
      antialias: false,
      preserveDrawingBuffer: true,  // needed for canvas.toDataURL() snap
      premultipliedAlpha: false,
      powerPreference: 'high-performance',
    });
    if (!gl) return null;
    if (!gl.getExtension('EXT_color_buffer_float')) {
      console.warn('EXT_color_buffer_float unavailable — HDR accumulation disabled.');
      return null;
    }

    const W = canvas.width;
    const H = canvas.height;

    const sceneProg   = linkProgram(gl, VS_SRC, FS_SCENE_SRC);
    const displayProg = linkProgram(gl, VS_SRC, FS_DISPLAY_SRC);
    const emptyVao    = gl.createVertexArray();
    const target      = createFBO(gl, W, H);

    const u = {
      res:     gl.getUniformLocation(sceneProg, 'u_resolution'),
      fstop:   gl.getUniformLocation(sceneProg, 'u_fstop'),
      shutter: gl.getUniformLocation(sceneProg, 'u_shutter'),
      iso:     gl.getUniformLocation(sceneProg, 'u_iso'),
      time:    gl.getUniformLocation(sceneProg, 'u_time'),
      seed:    gl.getUniformLocation(sceneProg, 'u_seed'),
      samples: gl.getUniformLocation(sceneProg, 'u_samples'),
      offset:  gl.getUniformLocation(sceneProg, 'u_sample_offset'),
    };
    const uDisp = {
      accum:       gl.getUniformLocation(displayProg, 'u_accum'),
      inv_samples: gl.getUniformLocation(displayProg, 'u_inv_samples'),
    };

    let accumulatedSamples = 0;

    function clearAccum() {
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      accumulatedSamples = 0;
    }

    function clearCanvas() {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }

    // Accumulate `samples` more ray samples into the FBO, then composite
    // the running mean to the canvas via the display shader.
    //   opts.fstop        — f-number (physical)
    //   opts.shutter_s    — shutter window in seconds (physical)
    //   opts.iso          — ISO gain (physical)
    //   opts.sceneTime    — seconds into the scene clock (for motion)
    //   opts.samples      — SPP added this call
    function accumulate(opts) {
      const N = Math.max(1, opts.samples | 0);

      gl.useProgram(sceneProg);
      gl.bindVertexArray(emptyVao);
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      gl.viewport(0, 0, W, H);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.uniform2f(u.res, W, H);
      gl.uniform1f(u.fstop, opts.fstop);
      gl.uniform1f(u.shutter, opts.shutter_s);
      gl.uniform1f(u.iso, opts.iso);
      gl.uniform1f(u.time, opts.sceneTime);
      gl.uniform1f(u.seed, Math.random() * 1000.0);
      gl.uniform1i(u.samples, N);
      gl.uniform1i(u.offset, accumulatedSamples);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.disable(gl.BLEND);

      accumulatedSamples += N;

      // Composite running mean → canvas.
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, W, H);
      gl.useProgram(displayProg);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, target.tex);
      gl.uniform1i(uDisp.accum, 0);
      gl.uniform1f(uDisp.inv_samples, 1.0 / Math.max(1, accumulatedSamples));
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindVertexArray(null);
    }

    return {
      canvas,
      accumulate,
      clearAccum,
      clearCanvas,
      get accumulatedSamples() { return accumulatedSamples; },
    };
  }

  // ---------- main orchestration ----------

  function onReady() {
    const liveCanvas  = document.getElementById('pad-live-canvas');
    const photoCanvas = document.getElementById('pad-photo-canvas');
    const fallback    = document.getElementById('pad-fallback');
    if (!liveCanvas || !photoCanvas) return;

    const live  = createRenderer(liveCanvas);
    const photo = createRenderer(photoCanvas);
    if (!live || !photo) {
      if (fallback) fallback.hidden = false;
      return;
    }

    // URL param ?N=32 overrides live SPP (for experimentation).
    const urlN = new URLSearchParams(window.location.search).get('N');
    const LIVE_SPP = urlN ? Math.max(1, Math.min(128, parseInt(urlN, 10) || INTERACTIVE_SPP))
                          : INTERACTIVE_SPP;
    const SNAP_MIN = readSnapMinOverride();

    // ---------- control inputs ----------
    const irisInput    = document.getElementById('pad-iris-input');
    const shutterInput = document.getElementById('pad-shutter-input');
    const isoInput     = document.getElementById('pad-iso-input');

    function fstopValue()       { return lerpIndex(IRIS_FSTOPS, irisInput ? +irisInput.value : 3); }
    function userShutterSeconds(){ return logLerpIndex(SHUTTER_SECS, shutterInput ? +shutterInput.value : 4); }
    function isoValue()         { return Math.round(logLerpIndex(ISO_VALUES, isoInput ? +isoInput.value : 2)); }

    // ---------- readout ----------
    const readoutF      = document.getElementById('readout-fstop');
    const readoutS      = document.getElementById('readout-shutter');
    const readoutI      = document.getElementById('readout-iso');
    const readoutStatus = document.getElementById('readout-status');
    const photoOverlay  = document.getElementById('pad-photo-overlay');
    const photoPlaceholder = document.getElementById('pad-photo-placeholder');
    const photoProgress = document.getElementById('pad-photo-progress');

    function updateReadout() {
      if (readoutF) readoutF.textContent = formatFstop(fstopValue());
      if (readoutS) readoutS.textContent = formatShutterReadout(userShutterSeconds());
      if (readoutI) readoutI.textContent = String(isoValue());
      if (readoutStatus) {
        if (snap.active) {
          const pct = Math.min(100, Math.round(photo.accumulatedSamples * 100 / snap.targetSpp));
          readoutStatus.textContent = `SNAP ${pct}%`;
          readoutStatus.classList.add('snapping');
        } else {
          readoutStatus.textContent = 'LIVE';
          readoutStatus.classList.remove('snapping');
        }
      }
      if (photoProgress) {
        if (snap.active) {
          const pct = Math.min(100, Math.round(photo.accumulatedSamples * 100 / snap.targetSpp));
          photoProgress.hidden = false;
          photoProgress.textContent = `developing · ${pct}%`;
        } else {
          photoProgress.hidden = true;
        }
      }
    }

    // ---------- album ----------
    // Session-scoped in-memory array; clears on page reload. IndexedDB
    // persistence is a follow-up can-slip (see roadmap #11).
    const album = [];
    const albumStrip = document.getElementById('pad-album-strip');
    const albumEmpty = document.getElementById('pad-album-empty');

    function captionHtmlFor(entry) {
      const fs = formatFstop(entry.fstop);
      const sh = formatShutterReadout(entry.shutter_s);
      const shPrefix = entry.shutter_s >= 1 ? '' : '1/';
      const shSuffix = entry.shutter_s >= 1 ? ' s' : ' s';
      return (
        '<span class="pad-caption-settings">' +
          '<span>f/' + fs + '</span>' +
          '<span>' + shPrefix + sh + shSuffix + '</span>' +
          '<span>ISO ' + entry.iso + '</span>' +
        '</span>'
      );
    }

    function shortCaption(entry) {
      const fs = formatFstop(entry.fstop);
      const sh = formatShutterReadout(entry.shutter_s);
      const shPrefix = entry.shutter_s >= 1 ? '' : '1/';
      return `f/${fs} · ${shPrefix}${sh}s · ISO${entry.iso}`;
    }

    function renderAlbum() {
      if (!albumStrip) return;
      albumStrip.innerHTML = '';
      if (albumEmpty) albumEmpty.dataset.hidden = album.length ? 'true' : 'false';
      for (const entry of album) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'pad-album-item';
        btn.setAttribute('role', 'listitem');
        btn.setAttribute('aria-label',
          `Captured photo at f/${formatFstop(entry.fstop)}, ` +
          `${formatShutterReadout(entry.shutter_s)}${entry.shutter_s >= 1 ? ' s' : ''}, ` +
          `ISO ${entry.iso}`);
        const img = document.createElement('img');
        img.src = entry.src;
        img.alt = 'Captured photo';
        const cap = document.createElement('span');
        cap.className = 'pad-album-caption';
        cap.textContent = shortCaption(entry);
        btn.appendChild(img);
        btn.appendChild(cap);
        btn.addEventListener('click', () => {
          if (typeof window.openImagePreview === 'function') {
            window.openImagePreview(entry.src, {
              alt: 'Captured photo',
              captionHtml: captionHtmlFor(entry),
              returnFocus: btn,
            });
          }
        });
        albumStrip.appendChild(btn);
      }
    }

    function pushAlbumEntry(entry) {
      album.push(entry);
      renderAlbum();
      if (photoPlaceholder) photoPlaceholder.hidden = false;
      if (photoOverlay) photoOverlay.dataset.hidden = 'false';
    }

    // ---------- snap state ----------
    const sceneT0 = performance.now();
    const sceneNow = () => (performance.now() - sceneT0) / 1000.0;

    const snap = {
      active: false,
      frozenTime: 0,
      fstop: 0,
      shutter_s: 0,
      iso: 0,
      targetSpp: 0,
    };

    function beginSnap() {
      snap.active     = true;
      snap.frozenTime = sceneNow();
      snap.fstop      = fstopValue();
      snap.shutter_s  = userShutterSeconds();
      snap.iso        = isoValue();
      snap.targetSpp  = targetSppForShutter(snap.shutter_s, SNAP_MIN);
      photo.clearAccum();
      photo.clearCanvas();
      if (photoOverlay) photoOverlay.dataset.hidden = 'true';
      updateReadout();
    }

    function finishSnap() {
      // Read the canvas pixels as a data URL — capture BEFORE flipping
      // any state, since preserveDrawingBuffer keeps the frame around.
      let src = '';
      try {
        src = photoCanvas.toDataURL('image/png');
      } catch (e) {
        console.error('Snap readout failed:', e);
      }
      const entry = {
        src,
        fstop: snap.fstop,
        shutter_s: snap.shutter_s,
        iso: snap.iso,
        timestamp: Date.now(),
      };
      snap.active = false;
      if (src) pushAlbumEntry(entry);
      updateReadout();
    }

    // ---------- control change → reset live accumulator + refresh readout.
    // Photo canvas is NOT touched: an in-flight snap keeps developing
    // with its frozen settings. If the user wants a different exposure
    // they press Snap again.
    const onControlChange = () => {
      // Live accumulator resets each frame anyway, but recompute readout.
      updateReadout();
    };
    if (irisInput)    irisInput.addEventListener('input', onControlChange);
    if (shutterInput) shutterInput.addEventListener('input', onControlChange);
    if (isoInput)     isoInput.addEventListener('input', onControlChange);

    // ---------- buttons + keyboard ----------
    const snapBtn  = document.getElementById('pad-snap-btn');
    const resetBtn = document.getElementById('pad-reset-btn');
    if (snapBtn) snapBtn.addEventListener('click', beginSnap);
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        if (irisInput)    { irisInput.value = '3';    irisInput.dispatchEvent(new Event('input', { bubbles: true })); }
        if (shutterInput) { shutterInput.value = '4'; shutterInput.dispatchEvent(new Event('input', { bubbles: true })); }
        if (isoInput)     { isoInput.value = '2';     isoInput.dispatchEvent(new Event('input', { bubbles: true })); }
        snap.active = false;
        photo.clearAccum();
        photo.clearCanvas();
        if (photoOverlay) photoOverlay.dataset.hidden = 'false';
        updateReadout();
      });
    }
    document.addEventListener('keydown', (e) => {
      if (e.key !== ' ' && e.key !== 'Spacebar') return;
      const t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault();
      beginSnap();
    });

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ---------- main loop ----------
    // Live runs every frame. Photo accumulates only while snap is active.
    function frame() {
      const tNow = sceneNow();

      // Live viewfinder: fresh render each frame at LIVE_SHUTTER_S.
      live.clearAccum();
      live.accumulate({
        fstop: fstopValue(),
        shutter_s: LIVE_SHUTTER_S,
        iso: isoValue(),
        sceneTime: reducedMotion ? 0.0 : tNow,
        samples: LIVE_SPP,
      });

      // Photo surface: advance the in-flight exposure, if any.
      if (snap.active && photo.accumulatedSamples < snap.targetSpp) {
        const remaining = snap.targetSpp - photo.accumulatedSamples;
        const step = Math.min(SNAP_PER_FRAME, remaining);
        photo.accumulate({
          fstop: snap.fstop,
          shutter_s: snap.shutter_s,
          iso: snap.iso,
          sceneTime: snap.frozenTime,
          samples: step,
        });
        updateReadout();
        if (photo.accumulatedSamples >= snap.targetSpp) finishSnap();
      }

      requestAnimationFrame(frame);
    }

    renderAlbum();
    updateReadout();
    photo.clearAccum();
    photo.clearCanvas();
    requestAnimationFrame(frame);
  }

  if (document.readyState !== 'loading') onReady();
  else document.addEventListener('DOMContentLoaded', onReady);
})();
