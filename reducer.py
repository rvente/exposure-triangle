"""Pure state-transition function for the Exposure Triangle app.

No I/O, no time.time(), no imports from Flask or SQLite. The caller injects
now_ms and any content the reducer needs (quiz answer key).

Scope: burn-in + adaptive-difficulty **v1** (HW12).

- **Burn-in (qid ≤ BURN_IN_QUIZZES):** fixed content for every user. After
  the third quiz locks, the reducer computes a proficiency score from the
  burn-in answers (`compute_proficiency` — 0.7·first-try-rate +
  0.3·latency-factor) and seeds the post-burn-in EWMA.
- **Post-burn-in activate (qid BURN_IN_QUIZZES+1 .. NUM_QUIZZES):** each
  locked answer feeds into an EWMA of per-question proficiency (α =
  EWMA_ALPHA). The bucket (`low` / `medium` / `high`) only shifts when the
  EWMA implies the same *different* bucket on **two consecutive**
  post-burn-in quizzes — damped to avoid flip-flopping.
- **Bonus path (qids in BONUS_QUIZ_IDS):** unlocks once the first
  BONUS_GATE_WINDOW answers (burn-in + first two activate) include at
  least BONUS_GATE_MIN_FIRST_TRY first-try corrects. On `advance_quiz`
  from the last main-flow quiz the reducer redirects to the first bonus
  question instead of `/result` if unlocked; otherwise straight to
  `/result`. Bonus qids are invisible to locked-out learners — the route
  itself is defined but `advance_quiz` never routes there.

See `ADAPTIVE_DIFFICULTY.md` for the full design. `static/js/reducer.js`
mirrors this file for the static (LocalBackend) build; Python is
authoritative for tests.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from typing import Any

NUM_LESSONS = 7
# Main-flow quiz count (what "Question N of M" shows to the learner during
# the activate phase). Bonus questions are additive — see BONUS_QUIZ_IDS.
NUM_QUIZZES = 8
BURN_IN_QUIZZES = 3

# Bonus qids are string-compared against `event["qid"]` in places, so keep
# them as strings. 9, 10 = the two bonus questions served only after a
# learner passes the gate.
BONUS_QUIZ_IDS: tuple[str, ...] = ("9", "10")
# Gate window = first N answers evaluated for the bonus check (burn-in +
# first two activate answers = 5). Threshold = minimum first-try-correct
# count required inside that window to unlock bonus.
BONUS_GATE_WINDOW = 5
BONUS_GATE_MIN_FIRST_TRY = 4

# EWMA smoothing factor for per-question proficiency updates. 0.3 weights
# the most recent answer at 30 % and the running estimate at 70 % — slow
# enough that a single fluke doesn't yank the bucket, fast enough that a
# genuine trend catches up within two or three quizzes.
EWMA_ALPHA = 0.3


@dataclass(frozen=True)
class State:
    session_id: str
    page: str = "home"
    page_index: int = 0
    page_entry_time_ms: int = 0
    answers: tuple = ()
    attempts: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)
    first_try_correct: dict = field(default_factory=dict)
    # proficiency: reported score — pre-burn-in = 0.0; at burn-in completion
    # = compute_proficiency(); post-burn-in = current EWMA. Mirrors
    # proficiency_ewma once the EWMA is seeded.
    proficiency: float = 0.0
    # proficiency_ewma: running exponentially-weighted moving average over
    # per-question post-burn-in contributions. Seeded from
    # compute_proficiency() at burn-in completion.
    proficiency_ewma: float = 0.0
    bucket: str = "medium"
    # pending_bucket + pending_bucket_count: damping machinery for the
    # two-consecutive-crossing rule. Each post-burn-in lock evaluates the
    # EWMA's preferred bucket; if different from `bucket` AND matches
    # `pending_bucket`, increment count; a count of 2 shifts `bucket`.
    pending_bucket: str = "medium"
    pending_bucket_count: int = 0
    # bonus_unlocked: sticky boolean set the first time the gate clears.
    # Never un-sets — once you've earned bonus, a revisit that drops your
    # first-try count can't take it away.
    bonus_unlocked: bool = False
    variant_selections: dict = field(default_factory=dict)


def new_state(session_id: str) -> State:
    return State(session_id=session_id)


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _latency_factor(latency_s: float) -> float:
    """5 s → 1.0, 15 s → 0.5, 25 s+ → 0.0. Linear clip."""
    return _clip(1.0 - (latency_s - 5.0) / 20.0, 0.0, 1.0)


def compute_proficiency(state: State) -> float:
    """Proficiency on [0, 1] computed from burn-in answers only.

    0.7 · first-try-rate + 0.3 · latency-factor, where latency-factor
    linearly interpolates from 1.0 at 5 s to 0.0 at 25 s of median burn-in
    latency. This is the seed value for the post-burn-in EWMA.
    """
    burn_in_ids = {str(i) for i in range(1, BURN_IN_QUIZZES + 1)}
    burn_in_answers = [a for a in state.answers if a["qid"] in burn_in_ids]
    if not burn_in_answers:
        return 0.0
    first_try_rate = sum(1 for a in burn_in_answers if a.get("first_try_correct")) / len(burn_in_answers)
    latencies_s = [a.get("latency_ms", 0) / 1000.0 for a in burn_in_answers]
    median_s = statistics.median(latencies_s) if latencies_s else 0.0
    return 0.7 * first_try_rate + 0.3 * _latency_factor(median_s)


def _per_q_contribution(answer: dict) -> float:
    """Single-answer proficiency contribution used to update the EWMA.

    Same 0.7 / 0.3 mix as `compute_proficiency`, but with a single
    question's latency rather than the burn-in median. `first_try_correct`
    is the binary signal; retries count as 0 even if the final answer is
    right — the EWMA only rewards first-try mastery, matching the spec.
    """
    first_try = 1.0 if answer.get("first_try_correct") else 0.0
    latency_s = answer.get("latency_ms", 0) / 1000.0
    return 0.7 * first_try + 0.3 * _latency_factor(latency_s)


def _update_ewma(prev: float, contribution: float, alpha: float = EWMA_ALPHA) -> float:
    return alpha * contribution + (1.0 - alpha) * prev


def bucket_for(proficiency: float) -> str:
    if proficiency >= 0.75:
        return "high"
    if proficiency >= 0.4:
        return "medium"
    return "low"


def _evaluate_bonus_gate(answers: tuple) -> bool:
    """Sticky: bonus unlocks when the first BONUS_GATE_WINDOW answers hold
    at least BONUS_GATE_MIN_FIRST_TRY first-try corrects. Caller is
    responsible for OR-ing with the current `bonus_unlocked` flag so a
    later revisit can't retract the unlock.
    """
    if len(answers) < BONUS_GATE_WINDOW:
        return False
    window = answers[:BONUS_GATE_WINDOW]
    first_try = sum(1 for a in window if a.get("first_try_correct"))
    return first_try >= BONUS_GATE_MIN_FIRST_TRY


def _recompute_adaptive(state: State) -> dict:
    """Deterministically replay the full answer trace to derive
    `(proficiency, proficiency_ewma, bucket, pending_bucket,
    pending_bucket_count, bonus_unlocked)`. Replay-from-scratch is O(n)
    per update but n ≤ NUM_QUIZZES so it's cheap — the benefit is that
    revisits (which *replace* rather than append) stay consistent with a
    fresh sequence without any incremental patch-up logic.
    """
    burn_in_prof = compute_proficiency(state)
    burn_in_ids = {str(i) for i in range(1, BURN_IN_QUIZZES + 1)}
    burn_in_answers = [a for a in state.answers if a["qid"] in burn_in_ids]
    post_answers = [a for a in state.answers if a["qid"] not in burn_in_ids]

    if len(burn_in_answers) < BURN_IN_QUIZZES:
        # Burn-in incomplete: nothing downstream to compute yet.
        return {
            "proficiency": burn_in_prof,
            "proficiency_ewma": burn_in_prof,
            "bucket": bucket_for(burn_in_prof) if burn_in_answers else state.bucket,
            "pending_bucket": bucket_for(burn_in_prof) if burn_in_answers else state.pending_bucket,
            "pending_bucket_count": 0,
            "bonus_unlocked": state.bonus_unlocked,
        }

    # Burn-in complete: seed EWMA and damping state from burn-in proficiency.
    ewma = burn_in_prof
    bucket = bucket_for(burn_in_prof)
    pending = bucket
    pending_count = 0
    # Replay each post-burn-in answer in order, updating EWMA and running
    # the two-consecutive-crossing damping machinery.
    for a in post_answers:
        ewma = _update_ewma(ewma, _per_q_contribution(a))
        candidate = bucket_for(ewma)
        if candidate == bucket:
            pending = bucket
            pending_count = 0
        elif candidate == pending:
            pending_count += 1
            if pending_count >= 2:
                bucket = candidate
                pending = bucket
                pending_count = 0
        else:
            pending = candidate
            pending_count = 1

    unlocked = state.bonus_unlocked or _evaluate_bonus_gate(state.answers)
    # Report the EWMA as the current proficiency once post-burn-in starts;
    # before that, the burn-in one-shot is authoritative.
    report_prof = ewma if post_answers else burn_in_prof
    return {
        "proficiency": report_prof,
        "proficiency_ewma": ewma,
        "bucket": bucket,
        "pending_bucket": pending,
        "pending_bucket_count": pending_count,
        "bonus_unlocked": unlocked,
    }


def _select_variant(state: State, qid: str) -> str:
    """Pick the variant slug for `qid`. Burn-in always uses `burn_in`;
    post-burn-in (both main-flow activate AND bonus) uses the learner's
    current bucket. Unknown qids fall through to the current bucket too."""
    try:
        n = int(qid)
    except (TypeError, ValueError):
        n = 0
    if n <= BURN_IN_QUIZZES:
        return "burn_in"
    return state.bucket


def _next_main_or_bonus_or_result(state: State, now_ms: int) -> tuple[State, dict]:
    """Resolve the next destination after `advance_quiz`.

    Main flow (q1..NUM_QUIZZES) is linear. At the end of main flow we
    branch on `bonus_unlocked`: either hand off to the first bonus qid or
    skip straight to /result. Within the bonus track we walk through
    BONUS_QUIZ_IDS in order. Callers expect a (state, {"redirect": ...})
    tuple in every case.
    """
    idx = state.page_index

    # Still inside main flow — linear advance.
    if idx < NUM_QUIZZES:
        nxt = idx + 1
        return _transition_to_quiz(state, nxt, now_ms)

    # End of main flow. Route into bonus if unlocked, else to result.
    if idx == NUM_QUIZZES:
        if state.bonus_unlocked and BONUS_QUIZ_IDS:
            nxt = int(BONUS_QUIZ_IDS[0])
            return _transition_to_quiz(state, nxt, now_ms)
        return _transition_to_result(state, now_ms)

    # Inside the bonus track. BONUS_QUIZ_IDS defines the ordering.
    idx_str = str(idx)
    if idx_str in BONUS_QUIZ_IDS:
        pos = BONUS_QUIZ_IDS.index(idx_str)
        if pos + 1 < len(BONUS_QUIZ_IDS):
            nxt = int(BONUS_QUIZ_IDS[pos + 1])
            return _transition_to_quiz(state, nxt, now_ms)
        return _transition_to_result(state, now_ms)

    # Shouldn't happen, but fall through to result rather than loop.
    return _transition_to_result(state, now_ms)


def _transition_to_quiz(state: State, nxt: int, now_ms: int) -> tuple[State, dict]:
    ns = replace(state, page="quiz", page_index=nxt, page_entry_time_ms=now_ms)
    qid = str(nxt)
    if qid not in ns.variant_selections:
        new_selections = dict(ns.variant_selections)
        new_selections[qid] = _select_variant(ns, qid)
        ns = replace(ns, variant_selections=new_selections)
    return ns, {"redirect": f"/quiz/{nxt}"}


def _transition_to_result(state: State, now_ms: int) -> tuple[State, dict]:
    ns = replace(state, page="result", page_index=0, page_entry_time_ms=now_ms)
    return ns, {"redirect": "/result"}


def reduce(state: State, event: dict, now_ms: int, *, answer_key: dict[str, str] | None = None) -> tuple[State, dict]:
    """Return (new_state, response_payload).

    Events:
      - {"type": "start"}
      - {"type": "enter", "page": "learn"|"quiz"|"result", "index": int}
      - {"type": "advance_learn"}
      - {"type": "advance_quiz"}
      - {"type": "submit_answer", "qid": str, "choice": str}
    """
    et = event.get("type")

    if et == "start":
        ns = replace(state, page="intro", page_index=0, page_entry_time_ms=now_ms)
        return ns, {"redirect": "/intro"}

    if et == "enter":
        page = event["page"]
        idx = int(event.get("index", 0))
        ns = replace(state, page=page, page_index=idx, page_entry_time_ms=now_ms)
        if page == "quiz" and idx >= 1:
            qid = str(idx)
            if qid not in ns.variant_selections:
                new_selections = dict(ns.variant_selections)
                new_selections[qid] = _select_variant(ns, qid)
                ns = replace(ns, variant_selections=new_selections)
        return ns, {}

    if et == "advance_learn":
        idx = state.page_index
        if idx < NUM_LESSONS:
            nxt = idx + 1
            ns = replace(state, page="learn", page_index=nxt, page_entry_time_ms=now_ms)
            return ns, {"redirect": f"/learn/{nxt}"}
        ns = replace(state, page="quiz", page_index=1, page_entry_time_ms=now_ms)
        return ns, {"redirect": "/quiz/1"}

    if et == "submit_answer":
        if answer_key is None:
            raise ValueError("submit_answer requires answer_key")
        qid = str(event["qid"])
        choice = event["choice"]
        correct = answer_key.get(qid)
        is_correct = choice == correct

        prior_attempts = state.attempts.get(qid, 0)
        new_attempts = dict(state.attempts)
        new_attempts[qid] = prior_attempts + 1

        latency_ms = dict(state.latency_ms)
        first_try = dict(state.first_try_correct)
        if prior_attempts == 0:
            latency_ms[qid] = max(0, now_ms - state.page_entry_time_ms)
            first_try[qid] = is_correct

        # Second-chance mechanic: first wrong stays on page (not locked).
        # Correct or second wrong locks and records an answer.
        locked = is_correct or prior_attempts >= 1
        answers = state.answers
        if locked:
            new_entry = {
                "qid": qid,
                "choice": choice,
                "correct": is_correct,
                "attempts": prior_attempts + 1,
                "latency_ms": latency_ms.get(qid, 0),
                "first_try_correct": first_try.get(qid, False),
            }
            # Duolingo-style revisit semantics: if this qid already has an
            # entry (user came back through the chapter strip), REPLACE it
            # rather than append. This keeps `len(answers) <= NUM_QUIZZES`
            # so `compute_score` can never exceed total. A redo can upgrade
            # a wrong answer to right, but never downgrade a right one —
            # retention is rewarded, spam isn't.
            existing_idx = next(
                (i for i, a in enumerate(answers) if a["qid"] == qid), None
            )
            if existing_idx is None:
                answers = answers + (new_entry,)
            else:
                existing = answers[existing_idx]
                if existing["correct"] and not is_correct:
                    # No downgrade. Keep the correct entry, bump attempts
                    # so we still see the revisit in the trace.
                    preserved = dict(existing)
                    preserved["attempts"] = existing["attempts"] + 1
                    answers = tuple(
                        preserved if i == existing_idx else a
                        for i, a in enumerate(answers)
                    )
                else:
                    answers = tuple(
                        new_entry if i == existing_idx else a
                        for i, a in enumerate(answers)
                    )

        ns = replace(
            state,
            answers=answers,
            attempts=new_attempts,
            latency_ms=latency_ms,
            first_try_correct=first_try,
        )

        # Roll proficiency / EWMA / bucket / damping / bonus-gate forward.
        # Done on every submit (lock or not) so a second wrong answer that
        # locks updates the adaptive state too; `_recompute_adaptive` is
        # idempotent under replay so extra calls are safe.
        adapt = _recompute_adaptive(ns)
        ns = replace(ns, **adapt)

        response = {
            "correct": is_correct,
            "locked": locked,
            "attempt": prior_attempts + 1,
            "correct_choice": correct if locked else None,
        }
        return ns, response

    if et == "advance_quiz":
        # Recompute adaptive state one more time so `_select_variant` in
        # the upcoming transition sees the latest bucket. Important
        # because `_select_variant` runs inside `_transition_to_quiz`.
        adapt = _recompute_adaptive(state)
        staged = replace(state, **adapt)
        return _next_main_or_bonus_or_result(staged, now_ms)

    return state, {}


def compute_score(state: State) -> dict[str, Any]:
    """Total counts the main-flow questions always, plus bonus questions
    only if the learner actually reached bonus (answered at least one).
    This keeps the "X / Y" denominator honest: a learner who never unlocked
    bonus sees X/8, a learner who unlocked + completed sees Y/10."""
    bonus_answered = sum(1 for a in state.answers if a["qid"] in BONUS_QUIZ_IDS)
    total = NUM_QUIZZES + (len(BONUS_QUIZ_IDS) if bonus_answered > 0 else 0)
    correct = sum(1 for a in state.answers if a["correct"])
    first_try = sum(1 for a in state.answers if a.get("first_try_correct"))
    return {
        "correct": correct,
        "total": total,
        "first_try": first_try,
        "answers": list(state.answers),
    }
