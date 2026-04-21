// Backend interface + two implementations.
// FlaskBackend is used in-course. LocalBackend is a stub reserved for a
// post-course static port (IndexedDB + a ported reducer).

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
  async loadState() { throw new Error("LocalBackend not yet implemented — post-course port"); }
  async recordEvent(_event) { throw new Error("LocalBackend not yet implemented — post-course port"); }
  async reset() { throw new Error("LocalBackend not yet implemented — post-course port"); }
}

window.backend = window.IS_STATIC ? new LocalBackend() : new FlaskBackend();
