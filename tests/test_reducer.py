import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reducer import (
    BONUS_GATE_MIN_FIRST_TRY,
    BONUS_GATE_WINDOW,
    BONUS_QUIZ_IDS,
    BURN_IN_QUIZZES,
    EWMA_ALPHA,
    NUM_LESSONS,
    NUM_QUIZZES,
    bucket_for,
    compute_proficiency,
    compute_score,
    new_state,
    reduce,
)


# Answer key shared across tests. Covers every main-flow qid (1..NUM_QUIZZES)
# plus the bonus qids (9, 10). Kept in sync with reducer.js / data/quizzes.json.
ANSWER_KEY = {
    "1": "a", "2": "b", "3": "c", "4": "a", "5": "b",
    "6": "b", "7": "c", "8": "a",
    "9": "b", "10": "a",
}


def test_start_redirects_to_intro():
    s = new_state("sid")
    s2, resp = reduce(s, {"type": "start"}, 1000)
    assert s2.page == "intro"
    assert s2.page_index == 0
    assert s2.page_entry_time_ms == 1000
    assert resp["redirect"] == "/intro"


def test_advance_learn_walks_lessons_then_quiz():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "learn", "index": 1}, 0)
    for i in range(1, NUM_LESSONS):
        s, resp = reduce(s, {"type": "advance_learn"}, 1000 * i)
        assert resp["redirect"] == f"/learn/{i + 1}"
    s, resp = reduce(s, {"type": "advance_learn"}, 9999)
    assert resp["redirect"] == "/quiz/1"
    assert s.page == "quiz" and s.page_index == 1


def test_correct_first_try_locks_and_records():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 5000)
    s, resp = reduce(
        s,
        {"type": "submit_answer", "qid": "1", "choice": "a"},
        7000,
        answer_key=ANSWER_KEY,
    )
    assert resp["correct"] is True
    assert resp["locked"] is True
    assert resp["correct_choice"] == "a"
    assert s.first_try_correct["1"] is True
    assert s.latency_ms["1"] == 2000
    assert len(s.answers) == 1


def test_second_chance_first_wrong_does_not_lock():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, resp = reduce(
        s,
        {"type": "submit_answer", "qid": "1", "choice": "b"},
        1000,
        answer_key=ANSWER_KEY,
    )
    assert resp["correct"] is False
    assert resp["locked"] is False
    assert resp["correct_choice"] is None
    assert s.first_try_correct["1"] is False
    assert len(s.answers) == 0
    assert s.attempts["1"] == 1


def test_second_chance_second_wrong_locks_and_reveals():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "b"}, 500, answer_key=ANSWER_KEY)
    s, resp = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "c"}, 1000, answer_key=ANSWER_KEY)
    assert resp["correct"] is False
    assert resp["locked"] is True
    assert resp["correct_choice"] == "a"
    assert len(s.answers) == 1
    assert s.answers[0]["attempts"] == 2
    assert s.answers[0]["first_try_correct"] is False


def test_second_chance_second_attempt_correct_locks_records_not_first_try():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "b"}, 500, answer_key=ANSWER_KEY)
    s, resp = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "a"}, 1200, answer_key=ANSWER_KEY)
    assert resp["correct"] is True
    assert resp["locked"] is True
    assert s.answers[0]["correct"] is True
    assert s.answers[0]["first_try_correct"] is False
    assert s.answers[0]["attempts"] == 2


def test_advance_quiz_walks_through_to_result():
    # Walk the full main flow with the bonus gate deliberately blocked (too
    # many wrong-first answers in the first 5). Advance after the last
    # main-flow quiz should route to /result, not to a bonus page.
    s = new_state("sid")
    # Miss q1 and q2 on first try so the bonus window (first 5 answers)
    # holds at most 3 first-try corrects — below the gate threshold.
    sabotage_qids = {"1", "2"}
    for n in range(1, NUM_QUIZZES):
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": n}, 0)
        qid = str(n)
        if qid in sabotage_qids:
            s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": "z"}, 50, answer_key=ANSWER_KEY)
        s, _ = reduce(
            s,
            {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]},
            100,
            answer_key=ANSWER_KEY,
        )
        s, resp = reduce(s, {"type": "advance_quiz"}, 200)
        assert resp["redirect"] == f"/quiz/{n + 1}"
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": NUM_QUIZZES}, 0)
    s, _ = reduce(
        s,
        {"type": "submit_answer", "qid": str(NUM_QUIZZES), "choice": ANSWER_KEY[str(NUM_QUIZZES)]},
        100,
        answer_key=ANSWER_KEY,
    )
    s, resp = reduce(s, {"type": "advance_quiz"}, 200)
    assert s.bonus_unlocked is False
    assert resp["redirect"] == "/result"
    assert s.page == "result"


def test_compute_score_counts_correct_and_first_try():
    s = new_state("sid")
    # 3 correct on first try, 1 correct on second, 1 wrong locked
    for qid in ("1", "2", "3"):
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": int(qid)}, 0)
        s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 4}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "4", "choice": "b"}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "4", "choice": "a"}, 200, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 5}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "5", "choice": "a"}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "5", "choice": "a"}, 200, answer_key=ANSWER_KEY)
    score = compute_score(s)
    assert score["total"] == NUM_QUIZZES
    assert score["correct"] == 4
    assert score["first_try"] == 3


def test_quiz_redo_replaces_entry_not_appended():
    # Duolingo-style revisit: answering the same qid a second time after
    # it's already locked does not append a new answer entry. Keeps
    # `len(answers) <= NUM_QUIZZES` so score can't exceed total.
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "a"}, 100, answer_key=ANSWER_KEY)
    assert len(s.answers) == 1
    # Revisit — pick correct again
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 500)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "a"}, 600, answer_key=ANSWER_KEY)
    assert len(s.answers) == 1
    assert s.answers[0]["correct"] is True
    assert s.answers[0]["attempts"] == 2  # 1 original + 1 revisit submit


def test_quiz_redo_upgrade_wrong_to_right():
    # A user who got a question wrong locked can come back and correct it.
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "b"}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "c"}, 200, answer_key=ANSWER_KEY)
    assert s.answers[0]["correct"] is False
    # Revisit — give correct answer
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 1000)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "a"}, 1100, answer_key=ANSWER_KEY)
    assert len(s.answers) == 1
    assert s.answers[0]["correct"] is True
    # first_try_correct stays fixed to the original first-engagement result
    assert s.answers[0]["first_try_correct"] is False


def test_quiz_redo_no_downgrade():
    # A right answer is never downgraded by a subsequent wrong answer.
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "a"}, 100, answer_key=ANSWER_KEY)
    assert s.answers[0]["correct"] is True
    # Revisit — wrong answer
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 500)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "b"}, 600, answer_key=ANSWER_KEY)
    assert s.answers[0]["correct"] is True  # unchanged
    # attempts still bumped so the revisit leaves a trace
    assert s.answers[0]["attempts"] >= 2


def test_score_never_exceeds_total_after_revisits():
    # Full clean main-flow run, then revisit every quiz once more. No bonus.
    s = new_state("sid")
    main_ids = tuple(str(i) for i in range(1, NUM_QUIZZES + 1))
    for qid in main_ids:
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": int(qid)}, 0)
        s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]}, 100, answer_key=ANSWER_KEY)
    for qid in main_ids:
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": int(qid)}, 200)
        s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]}, 300, answer_key=ANSWER_KEY)
    score = compute_score(s)
    assert score["total"] == NUM_QUIZZES
    assert score["correct"] == NUM_QUIZZES
    assert score["correct"] <= score["total"]


def test_reserved_adaptive_fields_have_defaults():
    s = new_state("sid")
    assert s.proficiency == 0.0
    assert s.bucket == "medium"
    assert s.variant_selections == {}


# ─── Adaptive-difficulty v0 ──────────────────────────────────────────────

def _burn_in_three(correct: tuple[bool, bool, bool], latency_ms_each: int = 2000):
    """Walk through the first three quizzes. `correct[i]` decides whether the
    learner gets qid i+1 right on the first try (True) or submits wrong then
    right (False)."""
    s = new_state("sid")
    for i, was_right in enumerate(correct):
        qid = str(i + 1)
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": i + 1}, 0)
        if was_right:
            s, _ = reduce(
                s, {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]},
                latency_ms_each, answer_key=ANSWER_KEY,
            )
        else:
            wrong = "z" if ANSWER_KEY[qid] != "z" else "y"
            s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": wrong},
                          latency_ms_each, answer_key=ANSWER_KEY)
            s, _ = reduce(
                s, {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]},
                latency_ms_each + 100, answer_key=ANSWER_KEY,
            )
    return s


def test_bucket_thresholds():
    assert bucket_for(0.0) == "low"
    assert bucket_for(0.39) == "low"
    assert bucket_for(0.4) == "medium"
    assert bucket_for(0.74) == "medium"
    assert bucket_for(0.75) == "high"
    assert bucket_for(1.0) == "high"


def test_proficiency_after_perfect_fast_burn_in_is_high():
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    prof = compute_proficiency(s)
    # 3/3 first-try, 3s median latency → latency_factor = 1.0 → prof = 1.0
    assert prof >= 0.99


def test_proficiency_after_mixed_burn_in_is_medium():
    # 2 first-try correct, 1 wrong-then-right; latency 4s each.
    s = _burn_in_three((True, False, True), latency_ms_each=4000)
    prof = compute_proficiency(s)
    # first_try_rate = 2/3; latency_factor = clip(1 - (4 - 5)/20, 0, 1) = 1.0
    # prof = 0.7 * (2/3) + 0.3 * 1.0 ≈ 0.767 → boundary case, could be high.
    # Tighten by using slower latency instead:
    s2 = _burn_in_three((True, False, True), latency_ms_each=10000)
    prof2 = compute_proficiency(s2)
    # first_try_rate = 2/3; latency_factor = clip(1 - (10-5)/20, 0, 1) = 0.75
    # prof = 0.7 * 0.667 + 0.3 * 0.75 ≈ 0.692 → medium
    assert bucket_for(prof2) == "medium"


def test_proficiency_after_slow_wrong_burn_in_is_low():
    s = _burn_in_three((False, False, False), latency_ms_each=30000)
    prof = compute_proficiency(s)
    # first_try_rate = 0; latency_factor = 0 → prof = 0.0
    assert prof == 0.0
    assert bucket_for(prof) == "low"


def test_enter_quiz_selects_burn_in_variant_for_first_three():
    s = new_state("sid")
    for i in (1, 2, 3):
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": i}, 0)
        assert s.variant_selections[str(i)] == "burn_in"


def test_advance_quiz_after_burn_in_computes_bucket_and_selects_variant():
    # Perfect burn-in → high bucket → q4 gets "high" variant.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    # Move from q3 to q4 via advance_quiz.
    s, resp = reduce(s, {"type": "advance_quiz"}, 0)
    assert resp["redirect"] == "/quiz/4"
    assert s.bucket == "high"
    assert s.proficiency >= 0.99
    assert s.variant_selections.get("4") == "high"


def test_advance_quiz_after_weak_burn_in_selects_low_variant():
    s = _burn_in_three((False, False, False), latency_ms_each=30000)
    s, _ = reduce(s, {"type": "advance_quiz"}, 0)
    assert s.bucket == "low"
    assert s.variant_selections.get("4") == "low"


def test_burn_in_variant_selection_survives_revisit():
    # Once a qid has a variant recorded, a later `enter` with the same qid
    # doesn't clobber the recorded selection (the reducer stays stable under
    # re-entry).
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    assert s.variant_selections["1"] == "burn_in"
    # Simulate state artificially promoted to high bucket (e.g. by a later
    # burn-in sweep), then re-enter q1.
    from dataclasses import replace as _replace
    s = _replace(s, bucket="high")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    # Burn-in quizzes always render the `burn_in` variant, so even if we
    # regenerated the selection now it would still be `burn_in`.
    assert s.variant_selections["1"] == "burn_in"


def test_burn_in_constant():
    assert BURN_IN_QUIZZES == 3


# ─── Adaptive-difficulty v1: EWMA + damping + bonus gate (HW12) ──────────

def _answer_main(s, qid: str, *, correct: bool, latency_ms: int = 2000, entry_ms: int = 0):
    """Emulate an entire quiz interaction (enter → submit). If `correct` is
    False, submits a wrong answer first (locks on 2nd wrong). Returns the
    state after the lock."""
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": int(qid)}, entry_ms)
    if correct:
        s, _ = reduce(
            s,
            {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]},
            entry_ms + latency_ms,
            answer_key=ANSWER_KEY,
        )
    else:
        wrong = "z" if ANSWER_KEY[qid] != "z" else "y"
        s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": wrong},
                      entry_ms + latency_ms, answer_key=ANSWER_KEY)
        s, _ = reduce(
            s,
            {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]},
            entry_ms + latency_ms + 100,
            answer_key=ANSWER_KEY,
        )
    return s


def test_ewma_seeds_from_burn_in_proficiency():
    # Perfect fast burn-in seeds the EWMA at the same value as the one-shot
    # burn-in proficiency (≈ 1.0). Post-burn-in the EWMA starts drifting.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    assert s.proficiency_ewma == compute_proficiency(s)
    assert s.proficiency == compute_proficiency(s)
    assert s.bucket == "high"


def test_ewma_decays_toward_weaker_performance():
    # After a strong burn-in, a slow-wrong post-burn-in answer should pull
    # the EWMA down toward the weaker per-question contribution. It's a
    # damped move, not a snap — we just check direction + magnitude.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    initial_ewma = s.proficiency_ewma
    s = _answer_main(s, "4", correct=False, latency_ms=30000)
    assert s.proficiency_ewma < initial_ewma
    # Single per-q contribution (wrong + slow) ≈ 0.0; EWMA = 0.3·0 + 0.7·1 = 0.7
    assert abs(s.proficiency_ewma - (EWMA_ALPHA * 0.0 + (1 - EWMA_ALPHA) * initial_ewma)) < 1e-9


def test_bucket_shift_requires_two_consecutive_crossings():
    # Start in high after perfect burn-in. One weak answer isn't enough to
    # demote; two consecutive weak answers wanting the same lower bucket
    # *is* enough. Damping spec: two-consecutive-crossing rule.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    assert s.bucket == "high"
    # First weak answer: EWMA drops but bucket stays (pending = medium/low, count=1).
    s = _answer_main(s, "4", correct=False, latency_ms=30000)
    assert s.bucket == "high", "single weak answer should not shift bucket"
    assert s.pending_bucket_count == 1
    # Second weak answer: same pending candidate → count hits 2 → shift.
    s = _answer_main(s, "5", correct=False, latency_ms=30000)
    assert s.bucket != "high", "two consecutive weak answers should shift bucket down"


def test_single_off_answer_does_not_shift_bucket():
    # Alternating strong/weak/strong should keep the bucket steady because
    # consecutive crossings never accumulate.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    assert s.bucket == "high"
    s = _answer_main(s, "4", correct=False, latency_ms=30000)  # weak
    s = _answer_main(s, "5", correct=True, latency_ms=3000)    # strong
    s = _answer_main(s, "6", correct=False, latency_ms=30000)  # weak
    # Even with weak answers interspersed, bucket should still be high —
    # the pending count resets whenever a strong answer re-endorses high.
    assert s.bucket == "high"


def test_bonus_gate_unlocks_at_four_of_five_first_try():
    # Perfect burn-in + 2 perfect post-burn-in = 5/5 first-try → unlocked.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    assert s.bonus_unlocked is False
    s = _answer_main(s, "4", correct=True, latency_ms=3000)
    assert s.bonus_unlocked is False  # only 4 answers, window not full yet
    s = _answer_main(s, "5", correct=True, latency_ms=3000)
    assert s.bonus_unlocked is True
    assert BONUS_GATE_WINDOW == 5
    assert BONUS_GATE_MIN_FIRST_TRY == 4


def test_bonus_gate_stays_locked_at_three_of_five():
    # 3 first-try corrects out of the first 5 answers = below threshold.
    # Answers 1,2,4 first-try right; 3 and 5 wrong on first try.
    s = new_state("sid")
    s = _answer_main(s, "1", correct=True, latency_ms=3000)
    s = _answer_main(s, "2", correct=True, latency_ms=3000)
    s = _answer_main(s, "3", correct=False, latency_ms=3000)
    s = _answer_main(s, "4", correct=True, latency_ms=3000)
    s = _answer_main(s, "5", correct=False, latency_ms=3000)
    assert s.bonus_unlocked is False
    # And further strong post-gate answers don't retroactively unlock,
    # because the gate only looks at the first BONUS_GATE_WINDOW answers.
    s = _answer_main(s, "6", correct=True, latency_ms=3000)
    s = _answer_main(s, "7", correct=True, latency_ms=3000)
    assert s.bonus_unlocked is False


def test_bonus_gate_sticky_across_revisits():
    # Once bonus unlocks, a later wrong revisit of a burn-in question can
    # drop first_try_correct for that qid but the unlock stays sticky —
    # retention rewarded, not punished.
    s = _burn_in_three((True, True, True), latency_ms_each=3000)
    s = _answer_main(s, "4", correct=True, latency_ms=3000)
    s = _answer_main(s, "5", correct=True, latency_ms=3000)
    assert s.bonus_unlocked is True
    # Revisit q1 with wrong answer — attempts bump, but first_try stays True
    # on the preserved entry (no-downgrade rule). Even if the gate re-evals,
    # bonus_unlocked is sticky.
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 10000)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "z"}, 10500, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "z"}, 11000, answer_key=ANSWER_KEY)
    assert s.bonus_unlocked is True


def test_advance_quiz_from_last_main_routes_to_bonus_when_unlocked():
    # Walk to q8, unlock bonus along the way, and assert advance → /quiz/9.
    s = new_state("sid")
    for n in range(1, NUM_QUIZZES + 1):
        s = _answer_main(s, str(n), correct=True, latency_ms=3000)
    assert s.bonus_unlocked is True
    # Currently page_index is from the last submit's implicit state. Set
    # it explicitly via `enter` to simulate the user being on q8 and
    # clicking Advance.
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": NUM_QUIZZES}, 20000)
    s, resp = reduce(s, {"type": "advance_quiz"}, 21000)
    assert resp["redirect"] == f"/quiz/{BONUS_QUIZ_IDS[0]}"
    assert s.page == "quiz"
    assert str(s.page_index) == BONUS_QUIZ_IDS[0]


def test_advance_quiz_from_last_main_routes_to_result_when_locked_out():
    s = new_state("sid")
    # Sabotage the gate: wrong on q1 and q2 first try.
    sabotage = {"1", "2"}
    for n in range(1, NUM_QUIZZES + 1):
        qid = str(n)
        s = _answer_main(s, qid, correct=(qid not in sabotage), latency_ms=3000)
    assert s.bonus_unlocked is False
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": NUM_QUIZZES}, 20000)
    s, resp = reduce(s, {"type": "advance_quiz"}, 21000)
    assert resp["redirect"] == "/result"


def test_advance_quiz_through_bonus_track():
    # With bonus unlocked and learner at q9, advance goes to q10. From q10
    # advance terminates at /result.
    s = new_state("sid")
    for n in range(1, NUM_QUIZZES + 1):
        s = _answer_main(s, str(n), correct=True, latency_ms=3000)
    assert s.bonus_unlocked is True
    first_bonus = int(BONUS_QUIZ_IDS[0])
    second_bonus = int(BONUS_QUIZ_IDS[1])
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": first_bonus}, 20000)
    s, resp = reduce(s, {"type": "advance_quiz"}, 21000)
    assert resp["redirect"] == f"/quiz/{second_bonus}"
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": second_bonus}, 22000)
    s, resp = reduce(s, {"type": "advance_quiz"}, 23000)
    assert resp["redirect"] == "/result"


def test_bonus_quiz_variant_follows_bucket():
    # Bonus questions get the learner's current bucket too, same as
    # activate-path quizzes. No bonus-specific variant selection logic.
    s = new_state("sid")
    for n in range(1, NUM_QUIZZES + 1):
        s = _answer_main(s, str(n), correct=True, latency_ms=3000)
    assert s.bonus_unlocked is True
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": NUM_QUIZZES}, 20000)
    s, resp = reduce(s, {"type": "advance_quiz"}, 21000)
    first_bonus = BONUS_QUIZ_IDS[0]
    assert resp["redirect"] == f"/quiz/{first_bonus}"
    assert s.variant_selections[first_bonus] == s.bucket


def test_compute_score_includes_bonus_total_only_when_reached():
    # Main-flow-only: total = NUM_QUIZZES.
    s = new_state("sid")
    for n in range(1, NUM_QUIZZES + 1):
        s = _answer_main(s, str(n), correct=True, latency_ms=3000)
    assert compute_score(s)["total"] == NUM_QUIZZES

    # Now step into bonus and complete one bonus question.
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": int(BONUS_QUIZ_IDS[0])}, 20000)
    s, _ = reduce(s, {"type": "submit_answer", "qid": BONUS_QUIZ_IDS[0],
                      "choice": ANSWER_KEY[BONUS_QUIZ_IDS[0]]}, 23000, answer_key=ANSWER_KEY)
    # Bonus counts in total now.
    assert compute_score(s)["total"] == NUM_QUIZZES + len(BONUS_QUIZ_IDS)


def test_bonus_quiz_ids_constant():
    assert BONUS_QUIZ_IDS == ("9", "10")
    assert NUM_QUIZZES == 8


# ─── Data-integrity CI guards ────────────────────────────────────────────

def test_every_variant_shares_burn_in_correct_answer():
    """Documented LocalBackend constraint: every variant must agree with
    its `burn_in` on the correct-answer id. LocalBackend's JS reducer uses
    a fixed ANSWER_KEY (derived from burn_in correct answers) rather than
    a per-request variant lookup. A divergent variant would validate as
    "wrong" in the static build while the Flask path validates correctly
    — a silent divergence. This CI guard catches the class of bug at
    authoring time.
    """
    import json

    quizzes = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "quizzes.json").read_text()
    )
    for qid, quiz in quizzes.items():
        expected = quiz["burn_in"]["correct"]
        variants = quiz.get("variants") or {}
        for slug, variant in variants.items():
            assert variant["correct"] == expected, (
                f"q{qid} variant '{slug}': correct={variant['correct']!r} "
                f"diverges from burn_in={expected!r}. LocalBackend's fixed "
                f"ANSWER_KEY validates against burn_in, so divergent variants "
                f"will show 'wrong' in the static build. Either align the "
                f"variant to burn_in or extend reducer.js to thread per-request "
                f"answer keys."
            )


def test_every_post_burn_in_quiz_has_all_three_variants():
    """Post-burn-in quizzes (qids 4..NUM_QUIZZES plus bonus) should carry
    all three adaptive buckets so `_select_variant` never falls back to
    burn_in content for a non-burn-in qid. Regression guard for HW12
    content authoring completeness."""
    import json

    quizzes = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "quizzes.json").read_text()
    )
    expected_buckets = {"low", "medium", "high"}
    post_burn_in_qids = [str(i) for i in range(BURN_IN_QUIZZES + 1, NUM_QUIZZES + 1)]
    post_burn_in_qids += list(BONUS_QUIZ_IDS)
    for qid in post_burn_in_qids:
        assert qid in quizzes, f"quiz {qid} missing from quizzes.json"
        variants = quizzes[qid].get("variants") or {}
        missing = expected_buckets - set(variants.keys())
        assert not missing, (
            f"q{qid} missing variants: {sorted(missing)}. Every post-burn-in "
            f"qid must carry low/medium/high variants."
        )
