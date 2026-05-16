// Pure-JS unit tests for the scrub accumulator.
//
// Run under node --test (built-in, Node 20+):
//   node --test tests/js
// Or via the repo's `make test-js` target.

const test = require("node:test");
const assert = require("node:assert/strict");
const { createScrubAccumulator } = require("../../static/js/scrub.js");

test("rejects invalid construction", () => {
  assert.throws(() => createScrubAccumulator({ maxPx: 0, pxPerStep: 10 }));
  assert.throws(() => createScrubAccumulator({ maxPx: 100, pxPerStep: 0 }));
  assert.throws(() => createScrubAccumulator({ maxPx: -1, pxPerStep: 10 }));
});

test("begin seeds virtualPx clamped into range", () => {
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(150);
  assert.equal(a.virtualPx(), 150);
  assert.equal(a.value(), 3);

  a.begin(-20);
  assert.equal(a.virtualPx(), 0);
  assert.equal(a.value(), 0);

  a.begin(9999);
  assert.equal(a.virtualPx(), 400);
  assert.equal(a.value(), 8);
});

test("applyDelta does nothing when not dragging", () => {
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.applyDelta(100);
  assert.equal(a.virtualPx(), 0);
  assert.equal(a.isDragging(), false);
});

test("applyDelta accumulates inside range", () => {
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(100);
  a.applyDelta(25);
  a.applyDelta(25);
  assert.equal(a.virtualPx(), 150);
  assert.equal(a.value(), 3);
});

test("no-ratchet: overshoot past max clamps; single reverse unsticks", () => {
  // The critical property. If virtualPx were allowed to run free to
  // 10_000_000, the user would have to undo every one of those pixels
  // before the value budged. Clamping on virtualPx means a single -1px
  // immediately registers as a value decrease.
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(350);
  a.applyDelta(99999);         // WAY past the end
  assert.equal(a.virtualPx(), 400);
  assert.equal(a.value(), 8);

  a.applyDelta(-1);            // single reverse pixel
  assert.equal(a.virtualPx(), 399);
  // Should be less than the previous value (8). Not at "8 minus tiny
  // overshoot still clipped to 8" — actually less.
  assert.ok(a.value() < 8, `expected value < 8 after -1, got ${a.value()}`);
});

test("no-ratchet: overshoot past zero clamps; single forward unsticks", () => {
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(50);
  a.applyDelta(-99999);
  assert.equal(a.virtualPx(), 0);
  assert.equal(a.value(), 0);

  a.applyDelta(1);
  assert.equal(a.virtualPx(), 1);
  assert.ok(a.value() > 0);
});

test("end() stops subsequent deltas", () => {
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(200);
  a.applyDelta(50);
  a.end();
  a.applyDelta(100);
  // Still at the pre-end position.
  assert.equal(a.virtualPx(), 250);
  assert.equal(a.isDragging(), false);
});

test("setVirtualPx clamps and updates baseline without requiring a drag", () => {
  // Used by callers when an external event (keyboard arrow, click-to-
  // jump) moves the value; next drag must start from the updated spot
  // without ratcheting.
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.setVirtualPx(300);
  assert.equal(a.virtualPx(), 300);
  a.begin(300);
  a.applyDelta(-50);
  assert.equal(a.virtualPx(), 250);

  a.setVirtualPx(-999);
  assert.equal(a.virtualPx(), 0);
  a.setVirtualPx(9999);
  assert.equal(a.virtualPx(), 400);
});

test("ignores non-finite deltas without corrupting state", () => {
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(100);
  a.applyDelta(NaN);
  a.applyDelta(Infinity);
  a.applyDelta(undefined);
  assert.equal(a.virtualPx(), 100);

  a.applyDelta(25);
  assert.equal(a.virtualPx(), 125);
});

test("touchReverse flag is an option on attachScrubDrag (smoke)", () => {
  // The accumulator itself doesn't see touchReverse — it's consumed inside
  // attachScrubDrag, which takes `touchReverse: true` and negates the
  // deltaX for touch pointers before calling applyDelta. This test just
  // confirms the accumulator's pure math is unchanged by adding the flag.
  // The full touch-reverse behavior is covered end-to-end in
  // tests/test_scrub_dials_e2e.py::test_drum_drag_reversed_on_mobile_touch.
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(100);
  a.applyDelta(+50);
  a.applyDelta(-100); // caller (attachScrubDrag) would negate for touch
  assert.equal(a.virtualPx(), 50);
});

test("round-trip drag simulation matches expected fractional path", () => {
  // Simulate: start at idx 2 (px=100), drag right to past end, drag back
  // to idx 5 (px=250). The value along the path should never go
  // negative or exceed count-1.
  const a = createScrubAccumulator({ maxPx: 400, pxPerStep: 50 });
  a.begin(100);
  // forward past end
  for (let i = 0; i < 20; i++) a.applyDelta(30);
  assert.equal(a.virtualPx(), 400);
  // back to 250
  for (let i = 0; i < 5; i++) a.applyDelta(-30);
  assert.equal(a.virtualPx(), 250);
  assert.equal(a.value(), 5);
  a.end();
});
