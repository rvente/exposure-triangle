// Page wiring. Uses window.backend (from backend.js), not fetch directly.

$(function () {
  // Quiz interactions work via standard form POST on button click — Flask
  // renders the feedback + locked state server-side. JS here is minimal and
  // only mirrors state to sessionStorage for rehydrate on refresh.

  const $form = $("#quiz-form");
  if ($form.length) {
    try {
      const state = { qid: $form.data("qid"), locked: $form.data("locked") === true };
      sessionStorage.setItem("last-quiz", JSON.stringify(state));
    } catch (_) {}
  }
});
