// Pure scrub accumulator + DOM helpers.
//
// Blender-ish slider drag without pointer lock: we track a virtual pixel
// position that clamps to [0, maxPx], so overshoot past the ends does NOT
// build up invisible "debt" the user has to unwind. A small reverse motion
// after hitting the end immediately starts moving the value back.
//
// Cursor is hidden on <body> for the duration of the drag so the user
// doesn't see it frozen against the widget edge — then restored exactly
// where the mouse actually is on release. No pointer lock, no permissions
// prompt, no cursor teleport.
//
// Loaded as a classic <script> in the browser (exposes window.Scrub) AND
// as a CommonJS module under node --test (exposes module.exports) — same
// file, UMD-style wrapper.

(function () {
  "use strict";

  function clamp(x, lo, hi) {
    return x < lo ? lo : (x > hi ? hi : x);
  }

  function createScrubAccumulator(opts) {
    const maxPx = Number(opts.maxPx);
    const pxPerStep = Number(opts.pxPerStep);
    if (!(maxPx > 0)) throw new Error("scrub: maxPx must be > 0");
    if (!(pxPerStep > 0)) throw new Error("scrub: pxPerStep must be > 0");

    let virtualPx = 0;
    let dragging = false;

    return {
      begin(startPx) {
        virtualPx = clamp(Number(startPx) || 0, 0, maxPx);
        dragging = true;
      },
      applyDelta(deltaPx) {
        if (!dragging) return;
        const d = Number(deltaPx);
        if (!Number.isFinite(d)) return;
        virtualPx = clamp(virtualPx + d, 0, maxPx);
      },
      end() {
        dragging = false;
      },
      isDragging() { return dragging; },
      virtualPx() { return virtualPx; },
      // Fractional value in steps (0..count - 1 if pxPerStep = stripWidth / (count - 1)).
      value() { return virtualPx / pxPerStep; },
      setVirtualPx(px) {
        virtualPx = clamp(Number(px) || 0, 0, maxPx);
      },
    };
  }

  // Browser-only: attach the accumulator to a DOM element as a pointer
  // drag. Returns the accumulator so callers can query / setVirtualPx
  // imperatively on external changes (keyboard, click-to-jump).
  //
  // onDrag(fractionalValue, info) fires on every pointermove while dragging.
  // onCommit(fractionalValue) fires on pointerup after a drag.
  // onClick(clientX) fires on pointerup if movement stayed within clickThreshold.
  function attachScrubDrag(element, opts) {
    const {
      maxPx,
      pxPerStep,
      getCurrentPx,
      onDrag,
      onCommit,
      onClick,
      clickThreshold = 4,
      // Default off: cursor hiding ate pointermove time and surprised
      // users on desktop. Iris drum + every other widget now keeps
      // the cursor visible during drag.
      hideCursor = false,
      // When true, touch-pointer drags apply the delta in the opposite
      // direction from mouse drags. Kept for backwards-compat; the iris
      // drum used to opt into this, but now uses reverseDrag instead so
      // both pointer types feel the same.
      touchReverse = false,
      // When true, every drag delta is negated regardless of pointer
      // type. Use this for carousel-feel widgets (iris drum) where the
      // visible content should follow the finger / cursor — drag right
      // → content moves right, earlier items come into center.
      reverseDrag = false,
    } = opts;

    const acc = createScrubAccumulator({ maxPx, pxPerStep });
    let pressClientX = 0;
    let pressClientY = 0;
    // Sum of raw (un-negated) horizontal movement since pointerdown.
    // The reverseDrag/touchReverse flip is applied per tick when feeding
    // the accumulator — *never* baked into rawTotalMovement, because the
    // movementX === 0 fallback below subtracts rawTotalMovement from
    // (clientX - pressClientX), and the two sides have to agree on sign.
    // Earlier versions reused a single `totalMovement` for both jobs;
    // with reverseDrag=true that made the fallback compute jumps of
    // 2× the real distance every time movementX happened to be 0
    // (common on touch where the finger pauses or moves purely vertically),
    // producing the iris drum's "wildly skipping in the opposite direction"
    // feel on click-and-drag.
    let rawTotalMovement = 0;
    let savedCursor = "";
    let isTouchDrag = false;

    element.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      const startPx = typeof getCurrentPx === "function" ? getCurrentPx() : 0;
      acc.begin(startPx);
      pressClientX = e.clientX;
      pressClientY = e.clientY;
      rawTotalMovement = 0;
      isTouchDrag = e.pointerType === "touch";
      // setPointerCapture keeps pointermove + pointerup routing to this
      // element when the cursor wanders off the viewport mid-drag. It's
      // not pointer lock (no permission, cursor stays visible) and not
      // pointer vanishing (we don't override the cursor style). Just an
      // event-routing hint so the drag doesn't dead-end if the user
      // overshoots the strip.
      try { element.setPointerCapture(e.pointerId); } catch (_) {}
      element.classList.add("is-scrubbing");
    });

    element.addEventListener("pointermove", (e) => {
      if (!acc.isDragging()) return;
      // movementX is the frame-to-frame delta — Pointer Events Level 3.
      // Works without pointer lock and Playwright reports it correctly.
      // Fall back to (clientX - pressClientX) - rawTotalMovement when the
      // browser doesn't fill movementX (shouldn't happen in evergreen
      // engines, but belt-and-suspenders).
      let rawDx = typeof e.movementX === "number" && e.movementX !== 0
        ? e.movementX
        : (e.clientX - pressClientX) - rawTotalMovement;
      rawTotalMovement += rawDx;
      let dx = rawDx;
      if (reverseDrag || (touchReverse && isTouchDrag)) dx = -dx;
      acc.applyDelta(dx);
      if (typeof onDrag === "function") {
        onDrag(acc.value(), { virtualPx: acc.virtualPx(), event: e });
      }
    });

    const finish = (e) => {
      if (!acc.isDragging()) return;
      acc.end();
      element.classList.remove("is-scrubbing");
      if (hideCursor && e && e.pointerType === "mouse") {
        document.body.style.cursor = savedCursor;
      }
      const absMove = Math.abs(rawTotalMovement);
      if (onClick && absMove <= clickThreshold) {
        onClick(pressClientX, pressClientY);
      } else if (typeof onCommit === "function") {
        onCommit(acc.value());
      }
    };

    element.addEventListener("pointerup", finish);
    element.addEventListener("pointercancel", finish);

    return acc;
  }

  // Idle-hint registry. Each registered widget gets a timer that surfaces
  // its hint element (adds .visible) after `idleHintMs` of no interaction.
  // Pointer / keyboard events reset the timer; blur / pointerleave cancel
  // it. Designed for the roadmap's "supportive-hint timer" affordance —
  // the user gets a gentle nudge only after dwelling without acting.
  const idleHintMs = 4500;

  function registerIdleHint(el, hintEl, customMs) {
    if (!el || !hintEl) return { dispose() {} };
    const ms = Number(customMs) || idleHintMs;
    let timer = null;
    const show = () => hintEl.classList.add("visible");
    const hide = () => hintEl.classList.remove("visible");
    const reset = () => {
      hide();
      if (timer) clearTimeout(timer);
      timer = setTimeout(show, ms);
    };
    const cancel = () => {
      hide();
      if (timer) { clearTimeout(timer); timer = null; }
    };
    const onInteract = () => reset();
    el.addEventListener("pointerdown", onInteract);
    el.addEventListener("pointermove", onInteract);
    el.addEventListener("keydown", onInteract);
    el.addEventListener("focus", reset, true);
    el.addEventListener("blur", cancel, true);
    el.addEventListener("pointerenter", reset);
    el.addEventListener("pointerleave", cancel);
    return {
      dispose() {
        cancel();
        el.removeEventListener("pointerdown", onInteract);
        el.removeEventListener("pointermove", onInteract);
        el.removeEventListener("keydown", onInteract);
        el.removeEventListener("focus", reset, true);
        el.removeEventListener("blur", cancel, true);
        el.removeEventListener("pointerenter", reset);
        el.removeEventListener("pointerleave", cancel);
      },
    };
  }

  const api = { createScrubAccumulator, attachScrubDrag, registerIdleHint, idleHintMs };

  // UMD footer: browser window + Node CJS.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined") {
    window.Scrub = api;
  }
})();
