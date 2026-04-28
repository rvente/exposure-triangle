// Page wiring. Uses window.backend (from backend.js), not fetch directly.

function onReady(fn) {
  if (document.readyState !== "loading") fn();
  else document.addEventListener("DOMContentLoaded", fn);
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
function attachCompareViewer(el) {
  const overlay = el.querySelector(".compare-overlay");
  const handle = el.querySelector(".compare-handle");
  if (!overlay || !handle) return;
  let dragging = false;

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
    dragging = true;
    try { el.setPointerCapture(e.pointerId); } catch (_) {}
    setPct(pctFromEvent(e));
  });
  document.addEventListener("pointermove", (e) => { if (dragging) setPct(pctFromEvent(e)); });
  document.addEventListener("pointerup", () => { dragging = false; });
  document.addEventListener("pointercancel", () => { dragging = false; });
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
      if (t < 1) requestAnimationFrame(frame);
      else { input.value = String(target); onUpdate(target); }
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
  const label = document.getElementById("slider-label");
  if (!viewer || !input || !img || !label) return;
  let frames;
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) { return; }
  frames.forEach((f) => { const p = new Image(); p.src = staticUrl("/static/" + f.src); });
  function update(idx) {
    const f = frames[Math.max(0, Math.min(frames.length - 1, idx))];
    img.src = staticUrl("/static/" + f.src);
    img.alt = f.label;
    label.textContent = f.label;
  }
  attachSnapSlider(input, update);
}

function initToggleViewer() {
  const viewer = document.getElementById("toggle-viewer");
  const group = document.getElementById("toggle-group");
  const img = document.getElementById("toggle-image");
  const label = document.getElementById("toggle-label");
  if (!viewer || !group || !img || !label) return;
  let frames;
  try { frames = JSON.parse(viewer.dataset.frames); } catch (_) { return; }
  frames.forEach((f) => { const p = new Image(); p.src = staticUrl("/static/" + f.src); });
  group.querySelectorAll(".toggle-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = parseInt(btn.dataset.index, 10);
      const f = frames[idx];
      img.src = staticUrl("/static/" + f.src);
      img.alt = f.label;
      label.textContent = f.label;
      group.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
    });
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
  initToggleViewer();
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
