// Page wiring. Uses window.backend (from backend.js), not fetch directly.

function onReady(fn) {
  if (document.readyState !== "loading") fn();
  else document.addEventListener("DOMContentLoaded", fn);
}

// HDR display preference. Stored in localStorage as 'on' | 'off'.
// When on, hdrFrameUrl() rewrites bokeh_f*.avif sources to their PQ-encoded
// BT.2020 counterparts under renders/hdr/. Other lessons don't have HDR
// variants yet — they pass through. Toggle widgets ([data-hdr-toggle])
// on intro.html and the iris lesson read/write this same key.
const HDR_KEY = "etriangle_hdr_pref";
const HDR_REF_KEY = "etriangle_hdr_ref";    // reference f-stop for display-side gain
const HDR_PEAK_KEY = "etriangle_hdr_peak";  // gain ceiling
const HDR_EVT = "hdr-pref-change";

const HDR_REF_DEFAULT = 5.6;   // f/5.6 neutral midpoint — opening overexposes, closing underexposes
const HDR_PEAK_DEFAULT = 8;    // cap gain at 8× so f/1.2 vs f/5.6 = 4.67 stops doesn't blow out the panel

function getHdrPref() {
  try { return localStorage.getItem(HDR_KEY) === "on"; }
  catch (_) { return false; }
}
function setHdrPref(on) {
  try { localStorage.setItem(HDR_KEY, on ? "on" : "off"); } catch (_) {}
  document.documentElement.classList.toggle("hdr-on", !!on);
  window.dispatchEvent(new CustomEvent(HDR_EVT, { detail: { on: !!on } }));
}
function getHdrRef() {
  try {
    const v = parseFloat(localStorage.getItem(HDR_REF_KEY));
    return Number.isFinite(v) && v > 0 ? v : HDR_REF_DEFAULT;
  } catch (_) { return HDR_REF_DEFAULT; }
}
function getHdrPeak() {
  try {
    const v = parseFloat(localStorage.getItem(HDR_PEAK_KEY));
    return Number.isFinite(v) && v >= 1 ? v : HDR_PEAK_DEFAULT;
  } catch (_) { return HDR_PEAK_DEFAULT; }
}
function setHdrRef(v) {
  try { localStorage.setItem(HDR_REF_KEY, String(v)); } catch (_) {}
  window.dispatchEvent(new CustomEvent(HDR_EVT, { detail: { on: getHdrPref() } }));
}
function setHdrPeak(v) {
  try { localStorage.setItem(HDR_PEAK_KEY, String(v)); } catch (_) {}
  window.dispatchEvent(new CustomEvent(HDR_EVT, { detail: { on: getHdrPref() } }));
}
// Iris HDR set. /hdr-baked-5.6/ has the iris darkening pre-multiplied
// in linear space at refFstop=5.6 (so f/1.2 = 4.67×, f/5.6 = 1×, f/32
// = 0.175×) before the PQ encode. We bake instead of running gain via
// CSS filter at display time because filter:brightness() rasterizes
// through sRGB working space and clips HDR before the multiply lands.
// /hdr/ (raw scene-linear, NPL=100) stays available for a future
// WebGL/canvas path that can apply gain in a shader without sRGB drop.
const HDR_IRIS_DIR = "hdr-baked-5.6/";
// Motion HDR uses the +2 EV bake (encode_avif_pq_motion.sh with EV_OFFSET=2).
// The neutral hdr-motion/ pass read ~2 stops dim against the SDR rendering;
// the boost is applied in linear half-float space (scale_exr.py) before PQ
// encoding so HDR headroom survives end to end. Bokeh is intentionally NOT
// boosted — its per-fstop iris darkening already lands at the right midpoint.
const HDR_MOTION_DIR = "hdr-motion-ev2/";
// ISO-night HDR (lesson 5 sensitivity dial). Per-frame ISO gain (0/+3/+6 EV)
// + compositor noise are baked into the linear EXR by render_iso_night_exr.py
// — view_settings.exposure has no effect on EXR, so we fold the gain through
// a Multiply node in the compositor before write. Noise scales with gain so
// the noise-to-signal ratio at the display matches the SDR pass.
const HDR_ISO_NIGHT_DIR = "hdr-iso-night/";

// Each entry maps a filename pattern to the directory its HDR variant
// lives in (under the same parent dir as the SDR original). The HDR
// variant is always .avif (PQ BT.2020); the SDR original may be
// .png or .avif. Extend this when more scenes get an EXR → AVIF-PQ
// pass.
const HDR_DIR_MAP = [
  { match: /^bokeh_f[\d.]+\.(?:png|avif)$/,  dir: HDR_IRIS_DIR },
  { match: /^motion_s[\d.]+\.(?:png|avif)$/, dir: HDR_MOTION_DIR },
  { match: /^iso_night_(?:low|med|high)\.(?:png|avif)$/, dir: HDR_ISO_NIGHT_DIR },
];

function hdrFrameUrl(src) {
  if (!getHdrPref()) return src;
  const m = src.match(/^(.*\/)?([^/]+\.(?:png|avif))$/);
  if (!m) return src;
  const filename = m[2];
  for (const { match, dir } of HDR_DIR_MAP) {
    if (match.test(filename)) {
      // HDR variant is always .avif regardless of SDR's extension.
      const hdrName = filename.replace(/\.(?:png|avif)$/, ".avif");
      return (m[1] || "") + dir + hdrName;
    }
  }
  return src;
}
// Parse the f-stop number out of "…/bokeh_f<N>.{png,avif}", or null.
function fstopOf(src) {
  const m = src.match(/bokeh_f([\d.]+)\.(?:png|avif)$/);
  return m ? parseFloat(m[1]) : null;
}
// Display-side exposure gain for one frame. The HDR EXR pass renders all
// f-stops at scene-radiance (exposure=0), so the iris darkening lives
// here instead of being baked into the pixels:
//   gain = 2^(-log2(fstop / refFstop)) = refFstop / fstop
// refFstop is the neutral midpoint (default f/5.6) — wider apertures
// brighten, narrower ones darken. Capped at peakGain so very wide stops
// don't blow well past the display's headroom.
function hdrGainFor(fstop) {
  if (!fstop) return 1;
  const g = getHdrRef() / fstop;
  return Math.min(g, getHdrPeak());
}
// Apply the doc-level class as the script parses, so toggle chrome and
// any HDR-aware CSS doesn't flash the wrong state on first paint.
document.documentElement.classList.toggle("hdr-on", getHdrPref());

// Generic <img> HDR rewriter. Walks every image on the page, records the
// SDR src once in data-sdr-src, then sets src to hdrFrameUrl(sdr) based
// on the current pref. Re-runs on HDR_EVT so toggling propagates to
// quiz pages, lesson showcases, etc. — anywhere a plain <img> is
// server-rendered without specialized swap logic.
//
// Skip rules:
// - [data-slot]               → the slider / blend / compare imgs are
//                               managed by their own swap code; touching
//                               them here would race the slider's update.
// - [data-hdr-managed]        → escape hatch for any future widget that
//                               wants to opt out.
// - inside [data-hdr-test-grid] → /hdr-test pins specific HDR variant
//                                 paths per tile; rewriting would
//                                 re-prefix the directory.
function wireHdrImages() {
  const imgs = document.querySelectorAll(
    'img:not([data-slot]):not([data-hdr-managed])'
  );
  imgs.forEach((img) => {
    if (img.closest('[data-hdr-test-grid]')) return;
    const cur = img.getAttribute('src') || '';
    if (!img.dataset.sdrSrc && cur) img.dataset.sdrSrc = cur;
    if (!img.dataset.sdrSrc) return;
    const target = hdrFrameUrl(img.dataset.sdrSrc);
    if (img.getAttribute('src') !== target) img.src = target;
  });
}

// Debug HDR toggle in the bottom .page-nav, present on every page so
// the SDR/HDR variant choice can be flipped without bouncing through
// /intro/why-dark or the iris debug strip. Same data-hdr-toggle wiring
// the lesson-tied toggles use, so initHdrToggle() picks it up
// automatically. The --debug modifier dims the pill so it reads as a
// dev affordance rather than lesson chrome.
function injectDebugHdrToggle() {
  const nav = document.querySelector('.page-nav');
  if (!nav) return;
  if (nav.querySelector('.hdr-toggle--debug')) return;
  const tog = document.createElement('div');
  tog.className = 'hdr-toggle hdr-toggle--debug';
  tog.setAttribute('data-hdr-toggle', '');
  tog.setAttribute('data-debug-only', '');
  tog.setAttribute('aria-label', 'HDR debug toggle');
  tog.innerHTML =
    '<span class="hdr-toggle-label">HDR</span>' +
    '<div class="hdr-toggle-pill" role="group">' +
    '<button type="button" class="hdr-toggle-btn" data-hdr-mode="off" aria-pressed="false">SDR</button>' +
    '<button type="button" class="hdr-toggle-btn" data-hdr-mode="on" aria-pressed="false">HDR</button>' +
    '</div>';
  // Insert as the middle child so it centers between Previous and the
  // next/spacer. With justify-content: space-between on .page-nav the
  // middle item naturally floats to the center via the equal-gap rule.
  const first = nav.firstElementChild;
  if (first && first.nextSibling) {
    nav.insertBefore(tog, first.nextSibling);
  } else {
    nav.appendChild(tog);
  }
}

// Iris blend-mode debug control. Two options, both GPU-accelerated:
//   alpha — slot B alpha-composited over slot A. Smooth crossfade.
//   snap  — slot A's src jumps to the nearest integer frame. No blend.
// data-mode value on the stack is "blend" for alpha (the long-standing
// template default) or "snap". The earlier "plus-lighter" mode + N-slot
// stack were removed once the alpha-blend midfade gamma issue we'd been
// chasing turned out to be a JS double-attenuation bug — see
// HDR_PIPELINE.md "Investigation log — 2026-04-25".
const BLEND_MODE_KEY = "etriangle_iris_blend_mode";
const BLEND_MODE_EVT = "iris-blend-mode-changed";
const BLEND_MODE_DEFAULT = "alpha";
const BLEND_MODE_TO_DATA = {
  "alpha": "blend",
  "snap":  "snap",
};

function getBlendMode() {
  try {
    const v = localStorage.getItem(BLEND_MODE_KEY);
    return (v && BLEND_MODE_TO_DATA[v]) ? v : BLEND_MODE_DEFAULT;
  } catch (_) { return BLEND_MODE_DEFAULT; }
}

function setBlendMode(mode) {
  if (!BLEND_MODE_TO_DATA[mode]) mode = BLEND_MODE_DEFAULT;
  try { localStorage.setItem(BLEND_MODE_KEY, mode); } catch (_) {}
  document.documentElement.dataset.irisBlendMode = mode;
  // Swap data-mode on every blend-stack — the template marks them with
  // data-mode="blend", which we treat as "originally a blend stack" and
  // swap to whatever the user picked. Also sync any visible select.
  document.querySelectorAll('.image-stack').forEach((stack) => {
    if (stack.dataset.modeOriginal === undefined) {
      stack.dataset.modeOriginal = stack.dataset.mode || "";
    }
    if (stack.dataset.modeOriginal === "blend") {
      stack.dataset.mode = BLEND_MODE_TO_DATA[mode];
    }
  });
  document.querySelectorAll("[data-iris-blend-mode-select]").forEach((s) => {
    if (s.value !== mode) s.value = mode;
  });
  window.dispatchEvent(new CustomEvent(BLEND_MODE_EVT, { detail: { mode } }));
}
document.documentElement.dataset.irisBlendMode = getBlendMode();

function initBlendModeSelect() {
  const select = document.querySelector("[data-iris-blend-mode-select]");
  if (!select) return;
  select.value = getBlendMode();
  select.addEventListener("change", () => setBlendMode(select.value));
}

// Debug-element visibility. Press `d` (no modifiers, not while typing in
// a field) to toggle. State persists in localStorage so engineers don't
// have to re-tap on every refresh. CSS hides [data-debug-only] elements
// unless html.debug-revealed is set; cleaner than display:none in JS.
const DEBUG_KEY = "etriangle_debug_revealed";

function getDebugRevealed() {
  try { return localStorage.getItem(DEBUG_KEY) === "on"; }
  catch (_) { return false; }
}
function setDebugRevealed(on) {
  try { localStorage.setItem(DEBUG_KEY, on ? "on" : "off"); } catch (_) {}
  document.documentElement.classList.toggle("debug-revealed", !!on);
}
document.documentElement.classList.toggle("debug-revealed", getDebugRevealed());

function initDebugKey() {
  document.addEventListener("keydown", (e) => {
    if (e.key !== "d" && e.key !== "D") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    setDebugRevealed(!getDebugRevealed());
  });
}

// Mobile debug reveal: phones can't type 'd', so two extra triggers.
//   1. URL hash: #debug=on / #debug=off (bookmarkable, persists via
//      localStorage from initDebugKey's existing setter).
//   2. 5 rapid taps anywhere within 1.5s. Discoverable for the dev,
//      unlikely to misfire from real users (5-tap requires intent).
function initMobileDebugReveal() {
  // URL hash check on load + on hashchange (in case the user edits it
  // without a full reload).
  const applyHash = () => {
    const h = (location.hash || "").toLowerCase();
    if (h.includes("debug=on"))  setDebugRevealed(true);
    if (h.includes("debug=off")) setDebugRevealed(false);
  };
  applyHash();
  window.addEventListener("hashchange", applyHash);

  // Tap accumulator. Resets if a tap arrives more than 1500ms after
  // the previous one, so a slow series doesn't accidentally toggle.
  const TAP_WINDOW_MS = 1500;
  const TAP_THRESHOLD = 5;
  let taps = [];
  document.addEventListener("pointerdown", (e) => {
    // Only count touch + pen pointers — mouse clicks would be too easy
    // to misfire (and devs already have the 'd' key on desktop).
    if (e.pointerType !== "touch" && e.pointerType !== "pen") return;
    const now = (typeof performance !== "undefined" ? performance.now() : Date.now());
    taps = taps.filter((t) => now - t < TAP_WINDOW_MS);
    taps.push(now);
    if (taps.length >= TAP_THRESHOLD) {
      setDebugRevealed(!getDebugRevealed());
      taps = [];
    }
  });
}

// Resolve a /static-prefixed asset URL. In Flask the path stays "/static/...".
// In the frozen build, we rewrite "/static/..." → "../<n>../static/..." relative
// to the current page's depth, so deploys under any subdirectory (and file://)
// still resolve correctly.
function staticUrl(path) {
  if (!window.IS_STATIC || !path.startsWith("/static/")) return path;
  // pathname like "/", "/intro/", "/learn/2/" — strip trailing "/", split,
  // discard the leading empty segment. The remaining length is the number of
  // ".." hops needed to climb back to the build root.
  const segs = window.location.pathname.replace(/\/$/, "").split("/").filter(Boolean);
  const ups = "../".repeat(segs.length);
  return ups + path.slice(1);
}

// Compare slider (base/overlay A-B viewer) — used on the sensitivity lesson.
// Listeners live on `el` (not document); `setPointerCapture` on pointerdown
// guarantees the move/up stream stays on `el` even when the cursor leaves
// the viewer. Moving listeners off document avoids cross-widget coupling
// and stops a prior regression where drag appeared to "stall" partway
// through on some platforms. `touch-action: none` on `.compare-viewer`
// (see app.css) tells mobile browsers not to hijack the gesture as a
// scroll after a little vertical wander.
function attachCompareViewer(el) {
  const overlay = el.querySelector(".compare-overlay");
  const handle = el.querySelector(".compare-handle");
  if (!overlay || !handle) return;
  let dragging = false;
  let activePointer = -1;

  function setPct(pct) {
    pct = Math.max(0, Math.min(100, pct));
    overlay.style.clipPath = `inset(0 0 0 ${pct}%)`;
    handle.style.left = pct + "%";
  }
  function pctFromEvent(e) {
    const rect = el.getBoundingClientRect();
    return ((e.clientX - rect.left) / rect.width) * 100;
  }
  el.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    dragging = true;
    activePointer = e.pointerId;
    try { el.setPointerCapture(e.pointerId); } catch (_) {}
    setPct(pctFromEvent(e));
  });
  el.addEventListener("pointermove", (e) => {
    if (!dragging || e.pointerId !== activePointer) return;
    setPct(pctFromEvent(e));
  });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    activePointer = -1;
    try { el.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("lostpointercapture", () => { dragging = false; activePointer = -1; });
  const initial = parseFloat(el.dataset.initialPct);
  setPct(Number.isFinite(initial) ? initial : 50);
}

// Snap-on-release range slider — continuous dragging with an ease-out snap to
// the nearest integer step on release. onUpdate is called with the rounded
// index so the viewer image always shows a discrete state.
function attachSnapSlider(input, onUpdate) {
  input.step = "0.001";
  input.addEventListener("input", () => onUpdate(Math.round(+input.value)));
  input.addEventListener("change", () => {
    const target = Math.round(+input.value);
    const start = +input.value;
    if (start === target) { onUpdate(target); return; }
    const duration = 220;
    const t0 = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - t0) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      input.value = String(start + (target - start) * eased);
      // Dispatch so fractional-value consumers (iris blend, dial decimal
      // readout, tuner needle) animate through the snap — otherwise they'd
      // appear to teleport to the target after the rAF finishes.
      input.dispatchEvent(new Event("input", { bubbles: true }));
      if (t < 1) requestAnimationFrame(frame);
      else { input.value = String(target); onUpdate(target); input.dispatchEvent(new Event("input", { bubbles: true })); }
    }
    requestAnimationFrame(frame);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") e.preventDefault();
  });
}

function initSliderViewer() {
  const viewer = document.getElementById("slider-viewer");
  const input = document.getElementById("slider-input");
  const img = document.getElementById("slider-image");
  const label = document.getElementById("slider-label"); // optional — tuner uses tuner-read instead
  if (!viewer || !input || !img) return;
  let frames;
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) { return; }
  // Preload SDR + HDR variants so the toggle never decodes mid-flip.
  const resolved = (src) => staticUrl("/static/" + hdrFrameUrl(src));
  frames.forEach((f) => {
    const a = new Image(); a.src = staticUrl("/static/" + f.src);
    const hdr = hdrFrameUrl(f.src);
    if (hdr !== f.src) { const b = new Image(); b.src = staticUrl("/static/" + hdr); }
  });
  function update(idx) {
    const f = frames[Math.max(0, Math.min(frames.length - 1, idx))];
    fadeSwap(img, resolved(f.src), f.label);
    if (label) label.textContent = f.label;
  }
  // Re-paint when the global HDR toggle flips so the visible frame
  // catches the new variant without waiting for the next slider tick.
  window.addEventListener(HDR_EVT, () => update(parseInt(input.value, 10) || 0));
  window.addEventListener("storage", (e) => {
    if (e.key === HDR_KEY) update(parseInt(input.value, 10) || 0);
  });
  attachSnapSlider(input, update);
}

// Iris drum — reticle fixed in center, labels translate under it.
// Drag on the viewport pans the strip; release snaps to the nearest label.
// Mirrors the chosen index into the hidden #slider-input.
function initDrum() {
  const drum = document.getElementById("iris-drum");
  if (!drum) return;
  const viewport = drum.querySelector(".drum-viewport");
  const strip = drum.querySelector("[data-drum-strip]");
  const labels = Array.from(drum.querySelectorAll(".drum-label"));
  const readout = drum.querySelector("[data-drum-read]");
  const targetId = drum.dataset.targetInput;
  const input = targetId ? document.getElementById(targetId) : null;
  const count = labels.length;
  if (!viewport || !strip || !count) return;

  // Each label's center offset inside the strip (label[0] center is 40px because
  // label width is 80px; label[i] center is 40 + i*80). But we position .drum-strip
  // with `left: 50%` and translateX so that the *current* label is centered. So
  // the needed translateX is -((i * labelWidth) + labelWidth/2).
  const labelWidth = 80;
  const translateForIdx = (i) => -(i * labelWidth + labelWidth / 2);

  let idx = parseInt(drum.dataset.defaultIndex, 10) || 0;
  let currentTx = translateForIdx(idx);

  const setTransform = (tx, snap) => {
    strip.style.transition = snap ? "" : "none";
    strip.classList.toggle("snapping", !!snap);
    strip.style.transform = `translateX(${tx}px)`;
    currentTx = tx;
  };

  const txToIdx = (tx) => {
    const raw = -(tx + labelWidth / 2) / labelWidth;
    return Math.max(0, Math.min(count - 1, Math.round(raw)));
  };

  const applyActive = () => {
    labels.forEach((el, i) => el.classList.toggle("active", i === idx));
    drum.setAttribute("aria-valuenow", String(idx));
    if (readout && input) {
      // Read label from the slider-input's frame data via the slider-viewer,
      // which already has the rich label strings.
      const viewer = document.getElementById("slider-viewer");
      try {
        const frames = JSON.parse(viewer.dataset.frames);
        if (frames[idx]) readout.textContent = frames[idx].label;
      } catch (_) {}
    }
  };

  const commitIdx = (newIdx, snap) => {
    idx = Math.max(0, Math.min(count - 1, newIdx));
    setTransform(translateForIdx(idx), snap);
    applyActive();
    if (!input) return;
    if (snap) {
      // Ease the shared input from its current value (possibly fractional
      // from a drag, possibly integer from a prior rest state) to the
      // target idx, dispatching input events each rAF tick so blend-mode
      // stacks animate smoothly under keyboard steps + click-to-select.
      easeInputTo(input, idx);
    } else {
      const prev = input.value;
      input.value = String(idx);
      if (prev !== String(idx)) {
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
  };

  // Pointer drag via shared Scrub helper — gives us:
  //   - no-ratchet clamping (overshoot past either end doesn't build debt)
  //   - cursor hidden during mouse drag, restored on release (no pointer lock)
  //   - click-to-jump when the cursor barely moved between down and up
  // The accumulator models a virtual pixel position; we convert to a strip
  // translateX via `maxPx = (count - 1) * labelWidth`.
  const maxPx = (count - 1) * labelWidth;
  const pxPerStep = labelWidth;
  const vpxToTx = (vpx) => translateForIdx(0) - vpx; // vpx=0 → idx=0 tx
  Scrub.attachScrubDrag(viewport, {
    maxPx,
    pxPerStep,
    // Carousel feel on both pointer types: drag right → strip moves
    // right → earlier (lower-index) items slide into center. This
    // matches the mobile-touch behavior that felt correct; desktop
    // used to do the opposite scrubber direction which reads as
    // "inverted" to anyone used to swiping a gallery.
    reverseDrag: true,
    // Don't hide the cursor during drag — the cursor-vanish trick
    // was for a Blender-ish "no debt" feel but added pointermove
    // overhead and surprised users on desktop.
    hideCursor: false,
    getCurrentPx: () => Math.max(0, Math.min(maxPx, -(currentTx - translateForIdx(0)))),
    onDrag: (fval) => {
      setTransform(vpxToTx(fval * labelWidth), false);
      // Write fractional value so blend-mode stack interpolates between
      // adjacent frames during the drag.
      if (input && Math.abs((+input.value) - fval) > 0.005) {
        input.value = String(fval);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      const liveIdx = Math.round(fval);
      if (liveIdx !== idx) {
        idx = liveIdx;
        applyActive();
      }
    },
    onCommit: (fval) => commitIdx(Math.round(fval), true),
    onClick: (clientX) => {
      // Click-to-jump: map the press coordinate to a label index. The
      // viewport is centered on the strip, so the press X relative to
      // the viewport's midpoint tells us how many labels away the user
      // clicked.
      const r = viewport.getBoundingClientRect();
      const dx = clientX - (r.left + r.width / 2);
      commitIdx(idx + Math.round(dx / labelWidth), true);
    },
  });

  // Wheel/trackpad scroll on the drum is intentionally NOT captured.
  // Vertical scroll passes through to page scroll; the drum only
  // responds to click+drag and keyboard. Reasons:
  //   - The horizontal-scroll path felt choppy under N-slot mode (the
  //     extra accumulator + per-tick setTransform fight rAF on Pixel).
  //   - It conflated page scroll with drum scrub for users who landed
  //     on the iris page mid-scroll.
  //   - Drag is the primary interaction; wheel was a nice-to-have.

  // Keyboard.
  drum.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") { commitIdx(idx + 1, true); e.preventDefault(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { commitIdx(idx - 1, true); e.preventDefault(); }
    else if (e.key === "Home") { commitIdx(0, true); e.preventDefault(); }
    else if (e.key === "End") { commitIdx(count - 1, true); e.preventDefault(); }
  });

  // Click-to-select on a label.
  labels.forEach((el, i) => {
    el.addEventListener("click", () => commitIdx(i, true));
  });

  // External sync: if the slider-input is moved by something else, match.
  // Bail during a live drag — onDrag dispatches input events with the
  // *fractional* fval, and rounding mid-drag would yank the strip to the
  // nearest integer index every time fval crossed a label boundary,
  // fighting the live finger position and producing the "wildly skipping
  // in the opposite direction" feel. The accumulator already drives the
  // strip directly during the drag; external sync only matters when some
  // other widget is moving the value.
  if (input) {
    input.addEventListener("input", () => {
      if (viewport.classList.contains("is-scrubbing")) return;
      const newIdx = Math.round(+input.value);
      if (newIdx !== idx && newIdx >= 0 && newIdx < count) {
        idx = newIdx;
        setTransform(translateForIdx(idx), true);
        applyActive();
      }
    });
  }

  // Initial paint.
  setTransform(translateForIdx(idx), false);
  applyActive();
}

// Crossfade frame swap. Two <img>s live inside .image-stack: [data-slot="a"]
// + [data-slot="b"]. The stack's data-showing attribute controls which one
// has opacity 1 via CSS. To swap:
//   1. load the new src into the hidden slot
//   2. on load, flip data-showing — CSS transitions both opacities at once
// Prior img.src swap caused a dip to bg-1 between frames; this reads as a
// true crossfade.
//
// Skipped when the stack is in "blend" mode — initIrisBlend owns those
// opacity values directly and writes slot srcs on every fractional update.
function fadeSwap(img, newSrc, newAlt) {
  if (!img) return;
  const stack = img.closest(".image-stack");
  if (stack && stack.dataset.mode === "blend") {
    // Keep the primary img's alt in sync for screen readers; opacity + src
    // are driven by initIrisBlend.
    if (newAlt !== undefined) img.alt = newAlt;
    return;
  }
  if (!stack) {
    if (img.getAttribute("src") !== newSrc) img.src = newSrc;
    if (newAlt !== undefined) img.alt = newAlt;
    return;
  }
  if (newAlt !== undefined) img.alt = newAlt;

  const currentlyShowing = stack.dataset.showing || "a";
  const hiddenSlot = currentlyShowing === "a" ? "b" : "a";
  const hiddenImg = stack.querySelector(`img[data-slot="${hiddenSlot}"]`);
  if (!hiddenImg) {
    if (img.getAttribute("src") !== newSrc) img.src = newSrc;
    return;
  }
  if (hiddenImg.getAttribute("src") === newSrc) {
    stack.dataset.showing = hiddenSlot;
    return;
  }
  const flip = () => {
    stack.dataset.showing = hiddenSlot;
    hiddenImg.removeEventListener("load", flip);
  };
  hiddenImg.addEventListener("load", flip);
  hiddenImg.src = newSrc;
}

// Ease a numeric input from its current value to a target over `duration`,
// dispatching 'input' events each rAF tick. Used by the dial so discrete
// clicks animate through fractional values instead of jumping — which
// matters for blend-mode image stacks where intermediate fractional values
// drive a smooth per-frame opacity mix.
const EASE_INPUT_DUR = 220;
function easeInputTo(input, target, duration) {
  if (!input) return;
  const dur = duration || EASE_INPUT_DUR;
  const start = +input.value;
  if (!Number.isFinite(start) || Math.abs(start - target) < 0.0001) {
    input.value = String(target);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  const t0 = performance.now();
  // Cancel any prior ease on this input.
  if (input.__easeRaf) cancelAnimationFrame(input.__easeRaf);
  function frame(now) {
    const t = Math.min(1, (now - t0) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    input.value = String(start + (target - start) * eased);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    if (t < 1) {
      input.__easeRaf = requestAnimationFrame(frame);
    } else {
      input.value = String(target);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.__easeRaf = null;
    }
  }
  input.__easeRaf = requestAnimationFrame(frame);
}

// Blend stack — reads fractional #slider-input and mixes adjacent frames
// by opacity, shader-style. Slot A = frames[floor], slot B = frames[ceil];
// opacity(A) = 1-frac, opacity(B) = frac. Preloads all frames once at init.
// Apply a fixed source-directory prefix to a "renders/bokeh_f*.avif"-style
// src. Used by the iris HDR-compare strip where each tile is pinned to a
// specific variant ("sdr", "hdr-baked-5.6", "hdr-bright-baked-5.6") rather
// than following the global HDR toggle.
function fixedSourceUrl(src, dirOverride) {
  if (!dirOverride || dirOverride === "sdr") return src;
  const m = src.match(/^(.*\/)?(bokeh_f[\d.]+)\.(?:png|avif)$/);
  if (!m) return src;
  // Directories ending in "-png" hold the 16-bit PNG dump of the same
  // PQ-encoded data the AVIF encoder consumes — used by the iris-hdr-
  // compare debug strip to isolate whether splotches are AVIF-side or
  // source-side. Every other HDR variant directory is .avif.
  const ext = dirOverride.endsWith("-png") ? "png" : "avif";
  return (m[1] || "") + dirOverride + "/" + m[2] + "." + ext;
}

// Bind one image-stack (slot A + slot B) to the shared #slider-input and
// drive a fractional opacity blend between adjacent frames. If
// `sourceDirOverride` is null, the stack follows the global HDR toggle
// via hdrFrameUrl(); otherwise it pins to a specific variant directory.
function bindBlendStack(stack, frames, input, sourceDirOverride) {
  const slotA = stack.querySelector('img[data-slot="a"]');
  const slotB = stack.querySelector('img[data-slot="b"]');
  if (!slotA || !slotB || !input || !frames.length) return;
  const max = frames.length - 1;

  const urlFor = (i) => {
    const src = frames[Math.max(0, Math.min(max, i))].src;
    const out = sourceDirOverride === null
      ? hdrFrameUrl(src)
      : fixedSourceUrl(src, sourceDirOverride);
    return staticUrl("/static/" + out);
  };

  // Preload every frame this stack might show so blend steps don't request
  // + decode mid-drag. For the main stack (no override) we also preload the
  // HDR variant so the toggle doesn't flash.
  frames.forEach((f) => {
    const a = new Image(); a.src = urlFor(frames.indexOf(f));
    if (sourceDirOverride === null) {
      const hdrSrc = hdrFrameUrl(f.src);
      if (hdrSrc !== f.src) {
        const b = new Image(); b.src = staticUrl("/static/" + hdrSrc);
      }
    }
  });

  // Capture the template-set data-mode as the "original" so setBlendMode
  // can later swap it (only stacks that started as "blend" follow the
  // dropdown — non-blend stacks like toggle-viewer crossfade stay put).
  if (stack.dataset.modeOriginal === undefined) {
    stack.dataset.modeOriginal = stack.dataset.mode || "";
  }

  // Opacity is driven directly by fractional input.value; no CSS transition
  // on the slots.
  slotA.style.transition = "none";
  slotB.style.transition = "none";

  const update = () => {
    const fval = Math.max(0, Math.min(max, +input.value));
    const lo = Math.floor(fval);
    const hi = Math.min(Math.ceil(fval), max);
    const frac = fval - lo;
    const mode = stack.dataset.mode;

    // snap: only slot A is shown, src jumps to the nearest integer frame.
    // CSS hides slot B for this mode.
    if (mode === "snap") {
      const idx = Math.round(fval);
      const src = urlFor(idx);
      if (slotA.getAttribute("src") !== src) slotA.src = src;
      slotA.style.opacity = "1";
      slotB.style.opacity = "0";
      if (frames[idx]) slotA.alt = frames[idx].label;
      return;
    }

    // alpha blend (data-mode="blend"): slotB sits above slotA in CSS,
    // alpha-composited in sRGB space. Result = B·αB + A·αA·(1-αB); holding
    // αA = 1 keeps slot A's contribution linear (the αA = 1-frac version
    // earlier collapsed it to (1-frac)² and visibly darkened the midfade).
    // Still sRGB-space (not linear-light) so HDR midpoints are mildly
    // darker than a true linear blend — see HDR_PIPELINE.md for the math.
    const loSrc = urlFor(lo);
    const hiSrc = urlFor(hi);
    if (slotA.getAttribute("src") !== loSrc) slotA.src = loSrc;
    if (slotB.getAttribute("src") !== hiSrc) slotB.src = hiSrc;
    slotA.style.opacity = "1";
    slotB.style.opacity = String(frac);
    if (frac < 0.5 && frames[lo]) slotA.alt = frames[lo].label;
    else if (frames[hi]) slotA.alt = frames[hi].label;
  };

  input.addEventListener("input", update);
  // Only the main stack listens for HDR toggle changes — the compare
  // strip is pinned per-tile.
  if (sourceDirOverride === null) {
    window.addEventListener(HDR_EVT, update);
    window.addEventListener("storage", (e) => { if (e.key === HDR_KEY) update(); });
  }
  // Re-paint when blend mode flips (snap ↔ blend) so the slot visibility
  // and src re-sync immediately, not on the next slider tick.
  window.addEventListener(BLEND_MODE_EVT, update);
  update();
}

function initBlendStack() {
  const input = document.getElementById("slider-input");
  if (!input) return;

  // Main blend stack — wired the same way as before, follows global HDR
  // toggle. Frames come from the parent slider-viewer's data attribute.
  const viewer = document.getElementById("slider-viewer");
  if (viewer) {
    const mainStack = viewer.querySelector('.image-stack[data-mode="blend"]');
    if (mainStack) {
      let frames = [];
      try { frames = JSON.parse(viewer.dataset.frames); } catch (_) {}
      bindBlendStack(mainStack, frames, input, null);
    }
  }

  // HDR-variant compare strip — each tile is pinned to a specific source
  // directory ("sdr" / "hdr-baked-5.6" / "hdr-bright-baked-5.6") via
  // data-source-dir, so dragging the iris drum updates all three side by
  // side. data-frames is duplicated onto each tile by the template.
  document.querySelectorAll('[data-iris-hdr-compare]').forEach((stack) => {
    let frames = [];
    try { frames = JSON.parse(stack.dataset.frames || "[]"); } catch (_) {}
    bindBlendStack(stack, frames, input, stack.dataset.sourceDir || "sdr");
  });
}

// Wire the debug knobs that drive the display-side gain in HDR mode:
//   [data-hdr-ref]  — reference f-stop (gain = ref / fstop), default 5.6
//   [data-hdr-peak] — gain ceiling, default 8
// Live-updates broadcast HDR_EVT so the iris blend stack re-renders.
function initHdrDebugControls() {
  const refInput = document.querySelector("[data-hdr-ref]");
  const peakInput = document.querySelector("[data-hdr-peak]");
  if (refInput) {
    refInput.value = String(getHdrRef());
    refInput.addEventListener("input", () => {
      const v = parseFloat(refInput.value);
      if (Number.isFinite(v) && v > 0) setHdrRef(v);
    });
  }
  if (peakInput) {
    peakInput.value = String(getHdrPeak());
    peakInput.addEventListener("input", () => {
      const v = parseFloat(peakInput.value);
      if (Number.isFinite(v) && v >= 1) setHdrPeak(v);
    });
  }
}

// Wire any [data-hdr-toggle] segmented control to read/write HDR_KEY.
// Multiple widgets across pages stay in sync via the same localStorage
// key + HDR_EVT broadcast on this tab and `storage` event cross-tab.
function initHdrToggle() {
  const widgets = document.querySelectorAll("[data-hdr-toggle]");
  if (!widgets.length) return;
  const apply = (on) => {
    widgets.forEach((w) => {
      w.querySelectorAll("[data-hdr-mode]").forEach((btn) => {
        const wants = btn.dataset.hdrMode === "on";
        const active = wants === !!on;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
    });
  };
  apply(getHdrPref());
  widgets.forEach((w) => {
    w.querySelectorAll("[data-hdr-mode]").forEach((btn) => {
      btn.addEventListener("click", () => setHdrPref(btn.dataset.hdrMode === "on"));
    });
  });
  window.addEventListener(HDR_EVT, (e) => apply(e.detail.on));
  window.addEventListener("storage", (e) => {
    if (e.key === HDR_KEY) apply(e.newValue === "on");
  });
}

// Dial widget — click cycles forward; Shift+click or left-arrow cycles back.
// The dial mirrors its index into the hidden #toggle-group so existing
// LocalBackend + toggle plumbing keeps working.
function initDial() {
  const dials = document.querySelectorAll(".dial");
  if (!dials.length) return;
  dials.forEach((dial) => {
    let stops;
    try { stops = JSON.parse(dial.dataset.stops); } catch (_) { return; }
    const indicator = dial.querySelector(".dial-indicator");
    const readout = dial.querySelector("[data-dial-readout]");
    const count = stops.length;
    const startAngle = parseFloat(dial.dataset.start);
    const step = parseFloat(dial.dataset.step);
    let idx = parseInt(dial.dataset.index, 10) || 0;
    let syncing = false;   // skip re-dispatch when this render is a sync from external input

    const render = () => {
      const angle = startAngle + idx * step;
      if (indicator) indicator.style.transform = `translateX(-50%) rotate(${angle}deg)`;
      if (readout) readout.textContent = stops[idx].readout;
      dial.setAttribute("aria-valuenow", String(idx));
      dial.dataset.index = String(idx);
      // Mirror to a hidden range input (e.g. shutter dial → #slider-input),
      // easing through fractional values so blend-mode stacks animate.
      if (!syncing) {
        const targetId = dial.dataset.targetInput;
        if (targetId) {
          const input = document.getElementById(targetId);
          if (input) easeInputTo(input, idx);
        }
      }
      // Dispatch for viz binding + toggle-viewer listener.
      dial.dispatchEvent(new CustomEvent("dial:change", { detail: { index: idx, stop: stops[idx] }, bubbles: true }));
    };

    const step_to = (dir) => {
      idx = (idx + dir + count) % count;
      render();
    };

    dial.addEventListener("click", (e) => step_to(e.shiftKey ? -1 : 1));
    dial.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowUp") { step_to(1); e.preventDefault(); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowDown") { step_to(-1); e.preventDefault(); }
      else if (e.key === "Home") { idx = 0; render(); e.preventDefault(); }
      else if (e.key === "End") { idx = count - 1; render(); e.preventDefault(); }
    });

    // Continuous sync: during a drag the target input carries a fractional
    // value. Animate the indicator angle + (for shutter) interpolated
    // decimal-second readout smoothly. On snap-release the input lands on
    // an integer and this path rests there.
    const targetId = dial.dataset.targetInput;
    if (targetId) {
      const input = document.getElementById(targetId);
      if (input) {
        let seconds = null;
        try { seconds = input.dataset.seconds ? JSON.parse(input.dataset.seconds) : null; } catch (_) {}
        const formatSec = (s) => {
          if (!Number.isFinite(s) || s <= 0) return "";
          if (s < 1) return "1/" + Math.max(1, Math.round(1 / s)) + " s";
          return (s < 10 ? s.toFixed(1) : String(Math.round(s))) + " s";
        };
        input.addEventListener("input", () => {
          const fval = Math.max(0, Math.min(count - 1, +input.value));
          const angle = startAngle + fval * step;
          if (indicator) indicator.style.transform = `translateX(-50%) rotate(${angle}deg)`;
          if (readout) {
            if (seconds && seconds.length === count) {
              const lo = Math.floor(fval);
              const hi = Math.min(Math.ceil(fval), count - 1);
              const frac = fval - lo;
              const v = seconds[lo] + frac * (seconds[hi] - seconds[lo]);
              readout.textContent = formatSec(v);
            } else {
              const r = Math.round(fval);
              if (stops[r]) readout.textContent = stops[r].readout;
            }
          }
          const roundedIdx = Math.round(fval);
          if (roundedIdx !== idx) {
            idx = roundedIdx;
            dial.setAttribute("aria-valuenow", String(idx));
            dial.dataset.index = String(idx);
          }
        });
      }
    }

    render();
  });
}

// Control viz binding — when the slider, tuner, or dial changes, update the
// corresponding CSS custom property on the #viz-* element sitting top-right
// of the hero image. Each lesson shows one viz matching its concept.
function bindVizToControls() {
  const viz = document.querySelector(".control-viz");
  if (!viz) return;

  // --- Slider / tuner drives iris or shutter viz ---
  const input = document.getElementById("slider-input");
  if (input) {
    const max = parseInt(input.max, 10) || 1;
    const update = () => {
      const norm = Math.max(0, Math.min(1, (+input.value) / max));
      if (viz.id === "viz-iris") viz.style.setProperty("--iris-open", String(1 - norm));
      else if (viz.id === "viz-shutter") viz.style.setProperty("--shutter-open", String(norm));
      else if (viz.id === "viz-iso") viz.style.setProperty("--iso-heat", String(norm));
    };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
  }

  // --- Dial drives iso viz on sensitivity lesson ---
  const dial = document.querySelector(".dial");
  if (dial && viz.id === "viz-iso") {
    dial.addEventListener("dial:change", (e) => {
      const i = e.detail.index, count = parseInt(dial.dataset.count, 10) || 1;
      const norm = count > 1 ? i / (count - 1) : 0.5;
      viz.style.setProperty("--iso-heat", String(norm));
    });
  }
}

// Tuner widget — tick-marked strip that drives the hidden #slider-input.
// During drag writes a FRACTIONAL input.value so downstream readouts
// (dial decimal seconds, drum position) can interpolate smoothly. Fires
// 'change' only on pointerup — that's what triggers attachSnapSlider's
// rAF snap-to-integer for the image frame.
function initTuner() {
  const strip = document.getElementById("tuner-strip");
  const needle = document.getElementById("tuner-needle");
  const read = document.getElementById("tuner-read");
  const input = document.getElementById("slider-input");
  const viewer = document.getElementById("slider-viewer");
  if (!strip || !needle || !input || !viewer) return;
  let frames = [];
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) {}
  const max = parseInt(input.max, 10);

  const renderAt = (val) => {
    const clamped = Math.max(0, Math.min(max, val));
    const pct = max === 0 ? 0 : (clamped / max) * 100;
    needle.style.left = pct + "%";
    if (read) {
      const rounded = Math.round(clamped);
      if (frames[rounded]) read.textContent = frames[rounded].label;
    }
  };

  const writeFval = (fval) => {
    if (Math.abs((+input.value) - fval) > 0.0005) {
      input.value = String(fval);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    renderAt(fval);
  };

  const setFromClientX = (clientX) => {
    const rect = strip.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, clientX - rect.left));
    writeFval((x / rect.width) * max);
  };

  // Shared scrub accumulator. Strip width maps pixel-exact to [0, max] so
  // pxPerStep = stripWidth / max and maxPx = stripWidth. Dragging past
  // either end of the strip stays sticky without ratcheting; a small
  // reverse motion immediately unsticks.
  const getStripWidth = () => Math.max(1, strip.getBoundingClientRect().width);
  Scrub.attachScrubDrag(strip, {
    // maxPx / pxPerStep are read lazily each drag via getCurrentPx — the
    // strip can resize on window resize between drags. We still register
    // once with concrete numbers; the accumulator reads maxPx at begin.
    maxPx: getStripWidth(),
    pxPerStep: getStripWidth() / (max || 1),
    getCurrentPx: () => {
      const w = getStripWidth();
      return (Math.max(0, Math.min(max, +input.value)) / (max || 1)) * w;
    },
    onDrag: (fval) => writeFval(fval),
    onCommit: () => {
      // Kick attachSnapSlider's rAF snap — it reads current fractional
      // input.value and eases it to the nearest integer.
      input.dispatchEvent(new Event("change", { bubbles: true }));
    },
    onClick: (clientX) => {
      // The tuner always jumped to the click position; preserve that.
      setFromClientX(clientX);
      input.dispatchEvent(new Event("change", { bubbles: true }));
    },
  });

  // Any input-event driver updates the needle (keyboard on hidden input,
  // attachSnapSlider's easing ticks, dial sync).
  input.addEventListener("input", () => renderAt(+input.value));

  // Initial paint.
  renderAt(+input.value);
}

function initToggleViewer() {
  const viewer = document.getElementById("toggle-viewer");
  const img = document.getElementById("toggle-image");
  const label = document.getElementById("toggle-label");
  if (!viewer || !img || !label) return;
  let frames;
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) { return; }
  frames.forEach((f) => { const p = new Image(); p.src = staticUrl("/static/" + f.src); });

  const setIdx = (idx) => {
    const f = frames[Math.max(0, Math.min(frames.length - 1, idx))];
    if (!f) return;
    fadeSwap(img, staticUrl("/static/" + f.src), f.label);
    label.textContent = f.label;
  };

  // Legacy toggle-group (optional — may have been replaced by a dial).
  const group = document.getElementById("toggle-group");
  if (group) {
    group.querySelectorAll(".toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.index, 10);
        setIdx(idx);
        group.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
      });
    });
  }

  // Dial drives the same viewer.
  document.addEventListener("dial:change", (e) => {
    if (e && e.detail && typeof e.detail.index === "number") setIdx(e.detail.index);
  });
}

// ─── Static-mode form intercepts (frozen-flask build) ───────────────────────
// In static mode, every flow form's POST is replayed against LocalBackend
// instead of hitting Flask. Navigation uses the redirect from the reducer.

function staticNavigate(redirect) {
  // Reducer redirects look like "/intro", "/learn/2", "/quiz/3", "/result".
  // Frozen output puts them under <route>/index.html, so trailing "/" is
  // resolved by any HTTP server's directory-index logic.
  if (!redirect) return;
  if (redirect === "/") { window.location.href = "./"; return; }
  const path = redirect.endsWith("/") ? redirect : redirect + "/";
  window.location.href = path;
}

async function handleStaticFormSubmit(form, submitter) {
  const action = form.dataset.staticAction;
  if (!action || !window.IS_STATIC) return false;
  if (action === "start") {
    const r = await window.backend.recordEvent({ type: "start" });
    staticNavigate(r.redirect);
    return true;
  }
  if (action === "intro_advance") {
    // Press the Shutter → Why this site is dark (still on the intro chapter).
    staticNavigate("/intro/why-dark/");
    return true;
  }
  if (action === "dark_advance") {
    // Why this site is dark → first lesson. The why-dark slide is informational
    // — only the enter-learn-1 event needs to land for the reducer.
    await window.backend.recordEvent({ type: "enter", page: "learn", index: 1 });
    staticNavigate("/learn/1");
    return true;
  }
  if (action === "learn_advance") {
    const r = await window.backend.recordEvent({ type: "advance_learn" });
    staticNavigate(r.redirect);
    return true;
  }
  if (action === "quiz_advance") {
    const r = await window.backend.recordEvent({ type: "advance_quiz" });
    staticNavigate(r.redirect);
    return true;
  }
  if (action === "quiz_submit") {
    const choice = (submitter && submitter.name === "choice") ? submitter.value : null;
    if (!choice) return false;
    const qid = form.dataset.qid;
    const r = await window.backend.recordEvent({ type: "submit_answer", qid, choice });
    renderQuizFeedback(form, choice, r);
    return true;
  }
  if (action === "reset") return false; // result.html handles its own onsubmit
  return false;
}

function renderQuizFeedback(form, selected, response) {
  // Mirror the server-side quiz.html feedback rendering, in JS.
  const opts = form.querySelectorAll("[data-opt-id]");
  const correctChoice = form.dataset.correctChoice;

  if (response.locked) {
    opts.forEach((b) => {
      b.disabled = true;
      const id = b.dataset.optId;
      if (id === correctChoice) {
        b.classList.add("correct");
      } else if (id === selected && !response.correct) {
        b.classList.add("incorrect");
      }
    });
  } else if (!response.correct) {
    // First wrong: gray out the chosen wrong option, leave others interactive.
    opts.forEach((b) => {
      const id = b.dataset.optId;
      if (id === selected) {
        b.classList.add("disabled-wrong");
        b.disabled = true;
      }
    });
  }

  // Feedback message
  let msg = "";
  let cls = "";
  if (response.correct) {
    msg = form.dataset.msgCorrect;
    cls = "text-success";
  } else if (response.locked) {
    msg = form.dataset.msgReveal;
    cls = "text-danger";
  } else {
    msg = form.dataset.msgHint;
    cls = "text-warning";
  }

  let fb = form.querySelector("#quiz-feedback");
  if (!fb) {
    fb = document.createElement("div");
    fb.className = "quiz-feedback mt-3";
    fb.id = "quiz-feedback";
    form.appendChild(fb);
  }
  fb.innerHTML = `<div class="${cls}">${msg}</div>`;

  // Lock state + advance button
  form.dataset.locked = response.locked ? "true" : "false";
  if (response.locked && !document.getElementById("advance-btn")) {
    const nav = document.querySelector(".page-nav");
    if (nav) {
      // Replace the right-side spacer with an Advance form.
      const rightSpacer = nav.querySelector(".nav-spacer:last-child");
      const advanceForm = document.createElement("form");
      advanceForm.method = "post";
      advanceForm.className = "nav-form";
      advanceForm.dataset.staticAction = "quiz_advance";
      advanceForm.innerHTML = '<input type="hidden" name="action" value="advance"><button id="advance-btn" class="btn btn-primary" type="submit">Advance →</button>';
      advanceForm.addEventListener("submit", (e) => {
        e.preventDefault();
        handleStaticFormSubmit(advanceForm, null);
      });
      if (rightSpacer) rightSpacer.replaceWith(advanceForm);
      else nav.appendChild(advanceForm);
    }
  }
}

function interceptStaticForms() {
  if (!window.IS_STATIC) return;
  document.querySelectorAll("form[data-static-action]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      const submitter = e.submitter;
      // Async, but we need to preventDefault synchronously first.
      e.preventDefault();
      handleStaticFormSubmit(form, submitter).catch((err) => console.error(err));
    });
  });
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function renderStaticResult() {
  if (!window.IS_STATIC) return;
  const display = document.getElementById("score-display");
  if (!display) return;
  const score = window.backend.computeScore();
  display.textContent = `${score.correct} / ${score.total}`;
  const ft = document.getElementById("first-try");
  if (ft) ft.textContent = String(score.first_try);
  const R = window.Reducer;
  const BONUS_IDS = (R && R.BONUS_QUIZ_IDS) || window.BONUS_QIDS || [];
  // Per-question review render: walk the answer log, look up the quiz
  // block the learner saw (variant-aware), and render prompt + chosen +
  // correct + rationale. Mirrors the server-side per_q render in
  // result.html.
  const QUIZZES = window.QUIZZES || {};
  let state = {};
  try { state = (window.backend && window.backend._load && window.backend._load()) || {}; } catch (_) {}
  const variantSelections = state.variantSelections || {};
  const list = document.getElementById("per-question-list");
  if (list) {
    list.innerHTML = score.answers.map((a) => {
      const quiz = QUIZZES[a.qid] || {};
      const slug = variantSelections[a.qid];
      const block =
        (slug && slug !== "burn_in" && quiz.variants && quiz.variants[slug]) ||
        quiz.burn_in || {};
      const optsById = {};
      (block.options || []).forEach((o) => { optsById[o.id] = o.text; });
      const chosenText = optsById[a.choice] != null ? optsById[a.choice] : "(no choice)";
      const correctText = optsById[block.correct] || "";
      const star = BONUS_IDS.includes(a.qid)
        ? ' <span class="badge bg-warning text-dark">★</span>' : '';
      const verdictBadge = a.correct
        ? '<span class="badge bg-success">correct</span>'
        : '<span class="badge bg-danger">wrong</span>';
      const promptLine = block.prompt
        ? `<div class="mb-2 fst-italic">${escapeHtml(block.prompt)}</div>` : '';
      const chosenLine = a.correct
        ? `<span class="text-success">${escapeHtml(chosenText)} ✓</span>`
        : `<span class="text-danger">${escapeHtml(chosenText)} ✗</span>`;
      const correctLine = !a.correct && correctText
        ? `<div class="mb-1"><strong>Correct answer:</strong> <span class="text-success">${escapeHtml(correctText)}</span></div>`
        : '';
      const whyLine = block.reveal_on_wrong
        ? `<div class="mt-2 text-muted small"><strong>Why:</strong> ${escapeHtml(block.reveal_on_wrong)}</div>`
        : '';
      return `
        <li class="list-group-item bg-transparent text-light">
          <div class="d-flex justify-content-between align-items-start mb-2 flex-wrap gap-2">
            <span><strong>Q${escapeHtml(a.qid)}</strong>${star}${quiz.category ? ` <span class="text-muted ms-2 small">${escapeHtml(quiz.category)}</span>` : ''}</span>
            <span class="d-flex gap-1 flex-wrap">
              ${verdictBadge}
              <span class="badge bg-secondary">attempts: ${a.attempts}</span>
              <span class="badge bg-secondary">${a.latency_ms} ms</span>
            </span>
          </div>
          ${promptLine}
          <div class="mb-1"><strong>Your answer:</strong> ${chosenLine}</div>
          ${correctLine}
          ${whyLine}
        </li>
      `;
    }).join("");
  }
  // Bonus celebration — frozen HTML is always rendered with fresh state
  // (bonus_reached=false) so the server-rendered banner never fires in
  // static mode. Inject the same copy client-side when LocalBackend
  // reports the learner actually completed at least one bonus qid.
  const bonusAnswered = score.answers.filter((a) => BONUS_IDS.includes(a.qid));
  if (bonusAnswered.length > 0 && !document.getElementById("bonus-celebration")) {
    const firstTryInWindow = score.answers
      .slice(0, 5)
      .filter((a) => a.first_try_correct).length;
    const banner = document.createElement("div");
    banner.id = "bonus-celebration";
    banner.className = "alert alert-warning bg-transparent text-warning border-warning mb-4";
    banner.setAttribute("role", "status");
    banner.innerHTML =
      "<strong>★ Bonus round unlocked.</strong> You nailed " +
      firstTryInWindow +
      " of 5 on first try through the burn-in and first two activate quizzes — the threshold was 4. " +
      "Bonus questions earned you the last " + BONUS_IDS.length +
      " slot" + (BONUS_IDS.length !== 1 ? "s" : "") +
      " on your score line.";
    const firstTryP = document.getElementById("first-try");
    const anchor = firstTryP ? firstTryP.closest("p") : null;
    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(banner, anchor.nextSibling);
    }
  }
}

// ─── Chapter nav: inject "Bonus" pip when LocalBackend says unlocked ───────
// Mirrors the Flask context_processor in app.py. The frozen build renders
// every page with base CHAPTERS (no Bonus pip) because freezing has no
// session context; when the user navigates, this helper reads LocalBackend
// state and patches the nav so the Bonus pip appears once they've
// earned it. No-op outside static mode (server already injected).
function injectBonusChapterIfUnlocked() {
  if (!window.IS_STATIC) return;
  const nav = document.querySelector(".chapter-nav .chapter-list");
  if (!nav) return;
  if (nav.querySelector('.chapter-item[data-slug="bonus"]')) return;
  let state;
  try { state = window.backend && window.backend._load && window.backend._load(); } catch (_) { return; }
  if (!state || !state.bonusUnlocked) return;
  const R = window.Reducer;
  const firstBonus = (R && R.BONUS_QUIZ_IDS && R.BONUS_QUIZ_IDS[0]) || "9";
  const items = Array.from(nav.querySelectorAll(".chapter-item"));
  const quizzesIdx = items.findIndex((li) => /\/quiz\/1\/?$/.test(li.querySelector("a")?.getAttribute("href") || ""));
  if (quizzesIdx < 0) return;
  const onBonusPage =
    /\/quiz\/(9|10)(\/|$)/.test(window.location.pathname);
  const activeClass = onBonusPage ? "active" : "upcoming";
  // Demote the Quizzes pip from active → passed if we're now on a bonus page.
  if (onBonusPage) {
    items[quizzesIdx].classList.remove("active");
    items[quizzesIdx].classList.add("passed");
  }
  const li = document.createElement("li");
  li.className = "chapter-item " + activeClass;
  li.dataset.slug = "bonus";
  li.style.setProperty("--chapter-delay", `${(quizzesIdx + 1) * 70}ms`);
  const anchor = document.createElement("a");
  anchor.href = firstBonus === "9" ? "../9/" : firstBonus;
  if (window.IS_STATIC) {
    // Resolve the href same way staticUrl does, relative to current page.
    const segs = window.location.pathname.replace(/\/$/, "").split("/").filter(Boolean);
    const ups = "../".repeat(segs.length);
    anchor.href = ups + "quiz/" + firstBonus + "/";
  }
  anchor.textContent = "Bonus";
  li.appendChild(anchor);
  items[quizzesIdx].after(li);
  // Trigger the progress sweep for the inserted item if the nav already
  // had `.progressed` applied on initial mount.
  const navRoot = document.querySelector(".chapter-nav");
  if (navRoot && navRoot.classList.contains("progressed")) {
    // Force a reflow so the delay restarts from 0 for the inserted segment.
    void li.offsetWidth;
  }
}

// ─── Brilliant-style paragraph reveal ──────────────────────────────────────
// Direct children of .slide-content fade in on a staggered delay when the
// page mounts. On first user interaction the remaining blocks snap in so
// nobody has to wait for the cascade if they're ready to move.
function prefersReducedMotion() {
  return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function cascadeReveal() {
  const shell = document.querySelector(".slide-content");
  if (!shell) return;
  const items = Array.from(shell.children);
  // `?reveal=off` (used by the atlas screenshot pipeline and any other
  // diagnostic tool that wants final-state rendering) short-circuits the
  // cascade. Same branch serves users with reduced-motion preferences.
  const off = new URLSearchParams(window.location.search).get("reveal") === "off";
  if (off || prefersReducedMotion()) {
    shell.classList.add("reveal-ready", "reveal-skip");
    return;
  }
  const STAGGER = 110;
  const OFFSET = 60;
  items.forEach((el, i) => {
    el.style.setProperty("--reveal-delay", `${OFFSET + i * STAGGER}ms`);
  });
  requestAnimationFrame(() => shell.classList.add("reveal-ready"));

  function skip() {
    shell.classList.add("reveal-skip");
    ["pointerdown", "keydown", "wheel", "touchstart"].forEach((ev) =>
      window.removeEventListener(ev, skip, { capture: true })
    );
  }
  ["pointerdown", "keydown", "wheel", "touchstart"].forEach((ev) =>
    window.addEventListener(ev, skip, { capture: true, passive: true })
  );
}

// ─── Idle-glow (60s dwell on the Advance button) ───────────────────────────
function initIdleGlow() {
  const btn = document.getElementById("advance-btn");
  if (!btn) return;
  const IDLE_MS = 60 * 1000;
  let timer = null;
  function schedule() {
    if (timer) clearTimeout(timer);
    btn.classList.remove("glow-nudge");
    timer = setTimeout(() => btn.classList.add("glow-nudge"), IDLE_MS);
  }
  const reset = () => schedule();
  ["pointerdown", "pointermove", "keydown", "scroll", "wheel", "touchstart"].forEach((ev) =>
    window.addEventListener(ev, reset, { passive: true })
  );
  schedule();
}

// ─── Auto-drift: widgets ping-pong through their range while idle ──────────
// The drift is purely visual — the reducer never sees these synthetic value
// changes. On any user interaction the drift cancels; 10s of quiescence
// restarts it from the user's current position.
//
// All active drifts are tracked in a registry so a single global listener
// (e.g. mousemove) can pause every widget at once — the user nudging the
// mouse anywhere on the page freezes every slider and A/B comparison until
// they've been still for the resume window.
const driftRegistry = [];

function notifyAllDrifts() {
  for (let i = 0; i < driftRegistry.length; i++) driftRegistry[i]();
}

function makeAutoDrift({ getCount, getIndex, setIndex, periodMs = 10000, resumeMs = 10000, markEl }) {
  if (prefersReducedMotion()) return;
  let rafId = null;
  let cancelled = false;
  let resumeTimer = null;

  function start(fromIdx) {
    if (cancelled) return;
    const count = getCount();
    if (count <= 1) return;
    if (markEl) markEl.classList.add("auto-drifting");
    const t0 = performance.now();
    const startIdx = fromIdx;
    function frame(now) {
      if (cancelled) return;
      const t = (now - t0) / periodMs; // full period = one ping-pong cycle
      // triangle wave 0..1..0 mapped across indices
      const phase = t - Math.floor(t);
      const tri = phase < 0.5 ? phase * 2 : (1 - phase) * 2;
      const span = count - 1;
      const idx = Math.round(((startIdx / span) + tri) % 1 * span);
      setIndex(idx);
      rafId = requestAnimationFrame(frame);
    }
    rafId = requestAnimationFrame(frame);
  }

  function stop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    if (markEl) markEl.classList.remove("auto-drifting");
  }

  function onInteract() {
    stop();
    if (resumeTimer) clearTimeout(resumeTimer);
    resumeTimer = setTimeout(() => {
      if (!cancelled) start(getIndex());
    }, resumeMs);
  }

  // Settle delay before the first drift. Generous enough that unit-style
  // page scripting (e.g. Playwright setting a slider value right after
  // mount) runs first and gets to cancel the drift via onInteract.
  setTimeout(() => start(getIndex()), 2500);

  driftRegistry.push(onInteract);

  return {
    onInteract,
    cancel() {
      cancelled = true;
      stop();
      if (resumeTimer) clearTimeout(resumeTimer);
      const i = driftRegistry.indexOf(onInteract);
      if (i >= 0) driftRegistry.splice(i, 1);
    },
  };
}

function attachSliderAutoDrift() {
  const viewer = document.getElementById("slider-viewer");
  const input = document.getElementById("slider-input");
  const img = document.getElementById("slider-image");
  const label = document.getElementById("slider-label");
  if (!viewer || !input || !img || !label) return;
  let frames;
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) { return; }
  const row = input.closest(".slider-row");
  const drift = makeAutoDrift({
    getCount: () => frames.length,
    getIndex: () => Math.round(+input.value),
    setIndex: (idx) => {
      const clamped = Math.max(0, Math.min(frames.length - 1, idx));
      input.value = String(clamped);
      const f = frames[clamped];
      img.src = staticUrl("/static/" + f.src);
      img.alt = f.label;
      label.textContent = f.label;
    },
    markEl: row,
  });
  if (!drift) return;
  ["pointerdown", "keydown", "focus", "input", "change"].forEach((ev) =>
    input.addEventListener(ev, drift.onInteract, { passive: true })
  );
}

function attachToggleAutoDrift() {
  const group = document.getElementById("toggle-group");
  const viewer = document.getElementById("toggle-viewer");
  const img = document.getElementById("toggle-image");
  const label = document.getElementById("toggle-label");
  if (!group || !viewer || !img || !label) return;
  let frames;
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) { return; }
  function activeIdx() {
    const btns = group.querySelectorAll(".toggle-btn");
    let idx = 0;
    btns.forEach((b, i) => { if (b.classList.contains("active")) idx = i; });
    return idx;
  }
  function setActive(idx) {
    const btns = group.querySelectorAll(".toggle-btn");
    btns.forEach((b, i) => {
      b.classList.toggle("active", i === idx);
    });
    const f = frames[idx];
    img.src = staticUrl("/static/" + f.src);
    img.alt = f.label;
    label.textContent = f.label;
  }
  const drift = makeAutoDrift({
    getCount: () => frames.length,
    getIndex: activeIdx,
    setIndex: setActive,
    markEl: viewer,
    periodMs: 9000,
  });
  if (!drift) return;
  group.querySelectorAll(".toggle-btn").forEach((btn) => {
    btn.addEventListener("pointerdown", drift.onInteract);
  });
}

function attachCompareAutoDrift() {
  const el = document.getElementById("compare-viewer");
  if (!el) return;
  const overlay = el.querySelector(".compare-overlay");
  const handle = el.querySelector(".compare-handle");
  if (!overlay || !handle) return;
  let pct = 50;
  const drift = makeAutoDrift({
    getCount: () => 101,
    getIndex: () => Math.round(pct),
    setIndex: (idx) => {
      pct = Math.max(0, Math.min(100, idx));
      overlay.style.clipPath = `inset(0 0 0 ${pct}%)`;
      handle.style.left = pct + "%";
    },
    markEl: el,
    periodMs: 11000,
  });
  if (!drift) return;
  el.addEventListener("pointerdown", drift.onInteract);
  // Keep pct in sync after user drags so the resume picks up the right start.
  const obs = new MutationObserver(() => {
    const match = /([0-9.]+)%/.exec(handle.style.left || "");
    if (match) pct = parseFloat(match[1]);
  });
  obs.observe(handle, { attributes: true, attributeFilter: ["style"] });
}

// Chapter-nav collapse on scroll (G4 item #8). Scroll down past a small
// threshold → retract the chapter nav upward. Scroll up at any point
// → restore it. rAF-throttled so pointer storms / fast wheels don't
// pile up work. Respects prefers-reduced-motion (kills the transform
// entirely — always visible).
function initChapterNavCollapse() {
  const nav = document.querySelector(".chapter-nav");
  if (!nav) return;
  if (prefersReducedMotion()) return;

  const COLLAPSE_AFTER_PX = 80;  // only retract once the learner actually scrolled
  const DELTA_THRESHOLD = 4;     // ignore jitter
  let lastY = window.scrollY;
  let pending = false;

  const onScroll = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const y = window.scrollY;
      const dy = y - lastY;
      if (Math.abs(dy) < DELTA_THRESHOLD) return;
      if (dy > 0 && y > COLLAPSE_AFTER_PX) {
        nav.classList.add("chapter-nav--collapsed");
      } else if (dy < 0) {
        nav.classList.remove("chapter-nav--collapsed");
      }
      lastY = y;
    });
  };
  window.addEventListener("scroll", onScroll, { passive: true });
}

// Floating bottom nav translucency (G4 item #7). While the user's
// pointer is over any text block inside .slide-content, the
// floating .page-nav fades (`.reading` class) so it doesn't occlude
// the line being read. An IntersectionObserver on the last child of
// .slide-content adds `.at-end` when that block enters the viewport,
// which overrides .reading and pins the nav to full opacity —
// matches the roadmap's "snaps back to fully opaque when the user
// reaches the end of the slide content" rule. Pointer events stay
// on regardless; this is purely visual.
function initFloatingNav() {
  const nav = document.querySelector(".page-nav");
  if (!nav) return;
  const slide = document.querySelector(".slide-content");
  if (!slide) return;

  // Enter/leave any text block → toggle .reading. `:scope > *` targets
  // the direct children of .slide-content (paragraphs, lists, images,
  // headings); that's the granularity that matters.
  const textTargets = Array.from(slide.querySelectorAll(":scope > *"))
    .filter((el) => !el.classList.contains("page-nav"));
  let hoverCount = 0;
  const bump = (d) => {
    hoverCount = Math.max(0, hoverCount + d);
    nav.classList.toggle("reading", hoverCount > 0);
  };
  textTargets.forEach((el) => {
    el.addEventListener("pointerenter", () => bump(+1));
    el.addEventListener("pointerleave", () => bump(-1));
  });

  // IntersectionObserver on the last text block — when it enters the
  // viewport, we're at the end of the content; force opaque.
  const last = textTargets[textTargets.length - 1];
  if (last && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        nav.classList.toggle("at-end", entry.isIntersecting);
      }
    }, { threshold: 0.25 });
    io.observe(last);
  } else {
    // Fallback: always show full opacity.
    nav.classList.add("at-end");
  }
}

// Fullscreen image preview (G4 item #6). On the duration lesson pages
// (/learn/2 showcase + /learn/3 slider) the learner can click an image
// to see it full-bleed. Escape / click-backdrop / close-X dismisses.
// Focus traps to the close button while open, returns to the trigger
// on close. When opened from the slider viewer, the modal subscribes
// to #slider-input and swaps its src to match the currently-selected
// (rounded) frame — dragging the tuner while the preview is open
// live-updates the hero. Also exposed as `window.openImagePreview()` /
// `window.closeImagePreview()` so `/pad` album thumbnails reuse the
// same modal without duplicating the scaffolding.
let __imagePreviewSingleton = null;
function _getImagePreview() {
  if (__imagePreviewSingleton) return __imagePreviewSingleton;

  let modal = document.getElementById("image-preview-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "image-preview-modal";
    modal.className = "image-preview-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "Image preview");
    modal.innerHTML =
      '<div class="image-preview-backdrop" data-preview-backdrop></div>' +
      '<figure class="image-preview-frame">' +
        '<img class="image-preview-img" alt="">' +
        '<figcaption class="image-preview-caption" data-preview-caption></figcaption>' +
      '</figure>' +
      '<button type="button" class="image-preview-close" ' +
        'aria-label="Close preview">&times;</button>';
    document.body.appendChild(modal);
  }
  const modalImg = modal.querySelector(".image-preview-img");
  const modalCaption = modal.querySelector("[data-preview-caption]");
  const closeBtn = modal.querySelector(".image-preview-close");
  const backdrop = modal.querySelector("[data-preview-backdrop]");

  let returnFocus = null;
  let sliderSubscription = null;

  function open(src, opts) {
    opts = opts || {};
    returnFocus = opts.returnFocus || null;
    modalImg.src = src;
    modalImg.alt = opts.alt || "";
    // Caption may be a string or an HTML fragment (used by the /pad
    // album to show an amber f/shutter/ISO readout under each photo).
    if (opts.captionHtml) {
      modalCaption.innerHTML = opts.captionHtml;
    } else {
      modalCaption.textContent = opts.caption || opts.alt || "";
    }
    modal.hidden = false;
    requestAnimationFrame(() => modal.classList.add("open"));
    closeBtn.focus();
    if (opts.trackSlider) {
      const input = document.getElementById("slider-input");
      const viewer = document.getElementById("slider-viewer");
      if (input && viewer) {
        let frames = [];
        try { frames = JSON.parse(viewer.dataset.frames); } catch (_) {}
        const handler = () => {
          const idx = Math.max(0, Math.min(frames.length - 1, Math.round(+input.value)));
          const f = frames[idx];
          if (f) {
            modalImg.src = staticUrl("/static/" + f.src);
            modalImg.alt = f.label;
            modalCaption.textContent = f.label;
          }
        };
        input.addEventListener("input", handler);
        sliderSubscription = () => input.removeEventListener("input", handler);
      }
    }
  }
  function close() {
    modal.classList.remove("open");
    modal.hidden = true;
    if (sliderSubscription) { sliderSubscription(); sliderSubscription = null; }
    const el = returnFocus;
    returnFocus = null;
    if (el && typeof el.focus === "function") el.focus();
  }

  closeBtn.addEventListener("click", close);
  backdrop.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (modal.hidden) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") {
      e.preventDefault();
      closeBtn.focus();
    }
  });

  __imagePreviewSingleton = { open, close, modal };
  return __imagePreviewSingleton;
}

// Expose programmatic entry points so other modules (e.g. /pad album
// thumbnails) can open the same modal without re-wiring triggers.
if (typeof window !== "undefined") {
  window.openImagePreview = function (src, opts) {
    _getImagePreview().open(src, opts || {});
  };
  window.closeImagePreview = function () {
    if (__imagePreviewSingleton) __imagePreviewSingleton.close();
  };
}

function initImagePreview() {
  // Triggers: showcase cards (on the /learn/2 duration-teaching page)
  // and the slider viewer IMG on /learn/3 (duration-interactive). The
  // tuner strip is the marker that distinguishes /learn/3 from /learn/1
  // (iris also uses #slider-image but doesn't have #tuner-strip).
  const hasTuner = !!document.getElementById("tuner-strip");
  const triggers = Array.from(document.querySelectorAll(".showcase-row img"));
  if (hasTuner) {
    const viewerImg = document.getElementById("slider-image");
    if (viewerImg) triggers.push(viewerImg);
  }
  if (!triggers.length) return;

  const { open } = _getImagePreview();

  // Wire triggers.
  triggers.forEach((trigger) => {
    trigger.style.cursor = "zoom-in";
    trigger.addEventListener("click", () => {
      const src = trigger.getAttribute("src");
      const alt = trigger.getAttribute("alt");
      // If the trigger is the slider viewer's main img on the
      // duration-interactive page, enable slider-tracking so scrubbing
      // updates the preview live.
      const trackSlider = trigger.id === "slider-image" && hasTuner;
      // Find the caption to show in the modal — for showcase cards it's
      // the sibling .showcase-label; for the slider viewer, it's the
      // alt text (same as slider frame label).
      let caption = alt;
      const card = trigger.closest(".showcase-card");
      if (card) {
        const labelEl = card.querySelector(".showcase-label");
        if (labelEl) caption = labelEl.textContent;
      }
      open(src, { alt, returnFocus: trigger, caption, trackSlider });
    });
    // Keyboard: Enter / Space on the img also opens.
    trigger.tabIndex = 0;
    trigger.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        trigger.click();
      }
    });
  });
}

onReady(function () {
  const form = document.getElementById("quiz-form");
  if (form) {
    try {
      const state = { qid: form.dataset.qid, locked: form.dataset.locked === "true" };
      sessionStorage.setItem("last-quiz", JSON.stringify(state));
    } catch (_) {}
  }
  document.querySelectorAll(".compare-viewer").forEach(attachCompareViewer);
  initSliderViewer();
  initTuner();
  initToggleViewer();
  initDial();
  initDrum();
  initBlendStack();
  // setBlendMode reads localStorage and rewrites every blend stack's
  // data-mode so the first user-triggered re-paint matches the saved
  // pref. Initial paint without it would briefly show the template default.
  setBlendMode(getBlendMode());
  initBlendModeSelect();
  injectDebugHdrToggle();
  initHdrToggle();
  initHdrDebugControls();
  // First HDR rewrite pass + subscribe to toggle changes. After this
  // every plain <img> on the page follows the global HDR pref.
  wireHdrImages();
  window.addEventListener(HDR_EVT, wireHdrImages);
  initDebugKey();
  initMobileDebugReveal();
  bindVizToControls();
  initImagePreview();
  initFloatingNav();
  initChapterNavCollapse();
  // Idle-hint registry: any widget that emits a sibling <.idle-hint
  // data-idle-hint-for="<widget-id>"> gets a timer that surfaces the
  // hint after ~4.5s of dwell with no interaction. Pointer / keyboard
  // activity resets; pointerleave / blur cancel. Only fires when the
  // user is paying attention to the widget.
  document.querySelectorAll(".idle-hint[data-idle-hint-for]").forEach((hint) => {
    const el = document.getElementById(hint.dataset.idleHintFor);
    if (el && window.Scrub && typeof window.Scrub.registerIdleHint === "function") {
      window.Scrub.registerIdleHint(el, hint);
    }
  });
  interceptStaticForms();
  renderStaticResult();
  injectBonusChapterIfUnlocked();
  // Kick the chapter-nav progress-bar fill-in. Done on next frame so the
  // initial zero-width state is committed before the transition to full.
  // `?reveal=off` (atlas screenshots) and reduced-motion skip the sweep
  // and jump straight to the final bar layout.
  const nav = document.querySelector(".chapter-nav");
  if (nav) {
    const instant =
      prefersReducedMotion() ||
      new URLSearchParams(window.location.search).get("reveal") === "off";
    if (instant) {
      nav.classList.add("progressed", "progressed-instant");
    } else {
      requestAnimationFrame(() => nav.classList.add("progressed"));
    }
  }
  cascadeReveal();
  initIdleGlow();
  attachSliderAutoDrift();
  attachToggleAutoDrift();
  attachCompareAutoDrift();

  // Any mouse (or touch) movement anywhere on the page counts as activity —
  // the drift on every widget pauses immediately and only resumes after the
  // cursor has been still for `resumeMs`. Throttled to one notify per
  // animation frame so pointer storms don't pile up work.
  let pendingMove = false;
  function onGlobalMove() {
    if (pendingMove || driftRegistry.length === 0) return;
    pendingMove = true;
    requestAnimationFrame(() => {
      pendingMove = false;
      notifyAllDrifts();
    });
  }
  window.addEventListener("mousemove", onGlobalMove, { passive: true });
  window.addEventListener("pointermove", onGlobalMove, { passive: true });
  window.addEventListener("touchmove", onGlobalMove, { passive: true });
});
