// Backend interface + two implementations.
// FlaskBackend talks to /api/* on the live Flask app.
// LocalBackend persists state in localStorage and runs the JS reducer (reducer.js)
// — used in the frozen-flask static build.

class Backend {
  async loadState() { throw new Error("abstract"); }
  async recordEvent(_event) { throw new Error("abstract"); }
  async submitAnswer(qid, choice) { return this.recordEvent({ type: "submit_answer", qid, choice }); }
  async reset() { throw new Error("abstract"); }
}

class FlaskBackend extends Backend {
  async loadState() {
    const r = await fetch("/api/state");
    return r.json();
  }
  async recordEvent(event) {
    const r = await fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    });
    return r.json();
  }
  async reset() {
    const r = await fetch("/api/reset", { method: "POST" });
    return r.json();
  }
}

class LocalBackend extends Backend {
  constructor() {
    super();
    // Versioned key — bump on every state-shape change. `_v1` = HW10 shape;
    // `_v2` = HW12 additions (proficiency_ewma, pending_bucket*,
    // bonus_unlocked). Clients on an older key fall through to a fresh
    // session rather than deserialize into a partial shape.
    this.STORAGE_KEY = "exposure_triangle_state_v2";
  }
  _load() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (_) {}
    const sid = "local-" + Math.random().toString(36).slice(2, 12);
    return window.Reducer.newState(sid);
  }
  _save(state) {
    try { localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state)); } catch (_) {}
  }
  async loadState() {
    const s = this._load();
    return {
      session_id: s.sessionId,
      page: s.page,
      page_index: s.pageIndex,
      answers: s.answers,
    };
  }
  async recordEvent(event) {
    const state = this._load();
    const [next, response] = window.Reducer.reduce(state, event, Date.now());
    this._save(next);
    return response;
  }
  async reset() {
    try { localStorage.removeItem(this.STORAGE_KEY); } catch (_) {}
    return { ok: true };
  }
  computeScore() {
    return window.Reducer.computeScore(this._load());
  }
}

window.backend = window.IS_STATIC ? new LocalBackend() : new FlaskBackend();
