// JS port of reducer.py — used by LocalBackend in static (frozen-flask) mode.
// Keep this in sync with reducer.py. The Python is authoritative for tests;
// this JS exists so the static build works without a server.
//
// State shape (mirrors @dataclass State):
//   { sessionId, page, pageIndex, pageEntryTimeMs, answers,
//     attempts, latencyMs, firstTryCorrect,
//     proficiency, proficiencyEwma, bucket,
//     pendingBucket, pendingBucketCount, bonusUnlocked, variantSelections }

const NUM_LESSONS = 7;
const NUM_QUIZZES = 8;
const BURN_IN_QUIZZES = 3;
const BONUS_QUIZ_IDS = ["9", "10"];
const BONUS_GATE_WINDOW = 5;
const BONUS_GATE_MIN_FIRST_TRY = 4;
const EWMA_ALPHA = 0.3;

// Answer key for all main-flow + bonus quizzes. Variants are expected to
// match the burn_in correct choice (documented constraint; see
// data/quizzes.json). If that changes, LocalBackend needs a per-request
// lookup like the Flask path.
const ANSWER_KEY = {
  "1": "a", "2": "b", "3": "c", "4": "a", "5": "b",
  "6": "b", "7": "c", "8": "a",
  "9": "b", "10": "a",
};

function newState(sessionId) {
  return {
    sessionId,
    page: "home",
    pageIndex: 0,
    pageEntryTimeMs: 0,
    answers: [],
    attempts: {},
    latencyMs: {},
    firstTryCorrect: {},
    proficiency: 0.0,
    proficiencyEwma: 0.0,
    bucket: "medium",
    pendingBucket: "medium",
    pendingBucketCount: 0,
    bonusUnlocked: false,
    variantSelections: {},
  };
}

function clip(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

function latencyFactor(latencyS) {
  // 5s → 1.0, 15s → 0.5, 25s+ → 0.0. Linear clip.
  return clip(1.0 - (latencyS - 5.0) / 20.0, 0.0, 1.0);
}

function median(nums) {
  if (!nums.length) return 0;
  const sorted = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function isBurnInQid(qid) {
  const n = parseInt(qid, 10);
  return Number.isFinite(n) && n >= 1 && n <= BURN_IN_QUIZZES;
}

function computeProficiency(state) {
  // 0.7 · first-try-rate + 0.3 · latency-factor across burn-in answers.
  const burnIn = state.answers.filter((a) => isBurnInQid(a.qid));
  if (!burnIn.length) return 0.0;
  const firstTryRate = burnIn.filter((a) => a.first_try_correct).length / burnIn.length;
  const medianLatencyS = median(burnIn.map((a) => (a.latency_ms || 0) / 1000.0));
  return 0.7 * firstTryRate + 0.3 * latencyFactor(medianLatencyS);
}

function perQContribution(answer) {
  const firstTry = answer.first_try_correct ? 1.0 : 0.0;
  const latencyS = (answer.latency_ms || 0) / 1000.0;
  return 0.7 * firstTry + 0.3 * latencyFactor(latencyS);
}

function updateEwma(prev, contribution, alpha = EWMA_ALPHA) {
  return alpha * contribution + (1.0 - alpha) * prev;
}

function bucketFor(p) {
  if (p >= 0.75) return "high";
  if (p >= 0.4) return "medium";
  return "low";
}

function evaluateBonusGate(answers) {
  // Sticky gate: caller OR-s with current bonusUnlocked.
  if (answers.length < BONUS_GATE_WINDOW) return false;
  const window = answers.slice(0, BONUS_GATE_WINDOW);
  const firstTry = window.filter((a) => a.first_try_correct).length;
  return firstTry >= BONUS_GATE_MIN_FIRST_TRY;
}

function recomputeAdaptive(state) {
  // Deterministic replay: re-derive all adaptive state from the full
  // answer trace. Same shape / rules as `_recompute_adaptive` in Python.
  const burnInProf = computeProficiency(state);
  const burnInAnswers = state.answers.filter((a) => isBurnInQid(a.qid));
  const postAnswers = state.answers.filter((a) => !isBurnInQid(a.qid));

  if (burnInAnswers.length < BURN_IN_QUIZZES) {
    return {
      proficiency: burnInProf,
      proficiencyEwma: burnInProf,
      bucket: burnInAnswers.length ? bucketFor(burnInProf) : state.bucket,
      pendingBucket: burnInAnswers.length ? bucketFor(burnInProf) : state.pendingBucket,
      pendingBucketCount: 0,
      bonusUnlocked: state.bonusUnlocked,
    };
  }

  // Seed EWMA from burn-in proficiency, then replay post-burn-in answers.
  let ewma = burnInProf;
  let bucket = bucketFor(burnInProf);
  let pending = bucket;
  let pendingCount = 0;
  for (const a of postAnswers) {
    ewma = updateEwma(ewma, perQContribution(a));
    const candidate = bucketFor(ewma);
    if (candidate === bucket) {
      pending = bucket;
      pendingCount = 0;
    } else if (candidate === pending) {
      pendingCount += 1;
      if (pendingCount >= 2) {
        bucket = candidate;
        pending = bucket;
        pendingCount = 0;
      }
    } else {
      pending = candidate;
      pendingCount = 1;
    }
  }

  const unlocked = state.bonusUnlocked || evaluateBonusGate(state.answers);
  return {
    proficiency: postAnswers.length ? ewma : burnInProf,
    proficiencyEwma: ewma,
    bucket,
    pendingBucket: pending,
    pendingBucketCount: pendingCount,
    bonusUnlocked: unlocked,
  };
}

function selectVariant(state, qid) {
  const n = parseInt(qid, 10);
  if (Number.isFinite(n) && n >= 1 && n <= BURN_IN_QUIZZES) return "burn_in";
  return state.bucket;
}

function transitionToQuiz(state, nxt, nowMs) {
  const ns = { ...state, page: "quiz", pageIndex: nxt, pageEntryTimeMs: nowMs };
  const qid = String(nxt);
  if (!(qid in ns.variantSelections)) {
    ns.variantSelections = { ...ns.variantSelections, [qid]: selectVariant(ns, qid) };
  }
  return [ns, { redirect: `/quiz/${nxt}` }];
}

function transitionToResult(state, nowMs) {
  return [
    { ...state, page: "result", pageIndex: 0, pageEntryTimeMs: nowMs },
    { redirect: "/result" },
  ];
}

function nextMainOrBonusOrResult(state, nowMs) {
  const idx = state.pageIndex;
  // Still inside main flow.
  if (idx < NUM_QUIZZES) return transitionToQuiz(state, idx + 1, nowMs);
  // End of main flow: branch on bonus_unlocked.
  if (idx === NUM_QUIZZES) {
    if (state.bonusUnlocked && BONUS_QUIZ_IDS.length) {
      return transitionToQuiz(state, parseInt(BONUS_QUIZ_IDS[0], 10), nowMs);
    }
    return transitionToResult(state, nowMs);
  }
  // Inside bonus track.
  const idxStr = String(idx);
  const pos = BONUS_QUIZ_IDS.indexOf(idxStr);
  if (pos >= 0 && pos + 1 < BONUS_QUIZ_IDS.length) {
    return transitionToQuiz(state, parseInt(BONUS_QUIZ_IDS[pos + 1], 10), nowMs);
  }
  return transitionToResult(state, nowMs);
}

function reduce(state, event, nowMs) {
  const et = event && event.type;

  if (et === "start") {
    return [
      { ...state, page: "intro", pageIndex: 0, pageEntryTimeMs: nowMs },
      { redirect: "/intro" },
    ];
  }

  if (et === "enter") {
    const page = event.page;
    const idx = parseInt(event.index || 0, 10);
    const ns = { ...state, page, pageIndex: idx, pageEntryTimeMs: nowMs };
    if (page === "quiz" && idx >= 1) {
      const qid = String(idx);
      if (!(qid in ns.variantSelections)) {
        ns.variantSelections = { ...ns.variantSelections, [qid]: selectVariant(ns, qid) };
      }
    }
    return [ns, {}];
  }

  if (et === "advance_learn") {
    const idx = state.pageIndex;
    if (idx < NUM_LESSONS) {
      const nxt = idx + 1;
      return [
        { ...state, page: "learn", pageIndex: nxt, pageEntryTimeMs: nowMs },
        { redirect: `/learn/${nxt}` },
      ];
    }
    return [
      { ...state, page: "quiz", pageIndex: 1, pageEntryTimeMs: nowMs },
      { redirect: "/quiz/1" },
    ];
  }

  if (et === "submit_answer") {
    const qid = String(event.qid);
    const choice = event.choice;
    const correct = ANSWER_KEY[qid];
    const isCorrect = choice === correct;

    const priorAttempts = state.attempts[qid] || 0;
    const newAttempts = { ...state.attempts, [qid]: priorAttempts + 1 };
    const latencyMs = { ...state.latencyMs };
    const firstTry = { ...state.firstTryCorrect };
    if (priorAttempts === 0) {
      latencyMs[qid] = Math.max(0, nowMs - state.pageEntryTimeMs);
      firstTry[qid] = isCorrect;
    }

    const locked = isCorrect || priorAttempts >= 1;
    let answers = state.answers;
    if (locked) {
      const newEntry = {
        qid,
        choice,
        correct: isCorrect,
        attempts: priorAttempts + 1,
        latency_ms: latencyMs[qid] || 0,
        first_try_correct: !!firstTry[qid] && isCorrect,
      };
      // Duolingo-style revisit: replace any prior entry for this qid
      // instead of appending. Wrong→right upgrade is allowed, right→wrong
      // downgrade is not (retention rewarded, spam isn't). Keeps
      // `answers.length <= NUM_QUIZZES + BONUS_QUIZ_IDS.length` so
      // compute_score can't overshoot.
      const existingIdx = answers.findIndex((a) => a.qid === qid);
      if (existingIdx < 0) {
        answers = [...answers, newEntry];
      } else {
        const existing = answers[existingIdx];
        let replacement;
        if (existing.correct && !isCorrect) {
          replacement = { ...existing, attempts: existing.attempts + 1 };
        } else {
          replacement = newEntry;
        }
        answers = answers.map((a, i) => (i === existingIdx ? replacement : a));
      }
    }

    let ns = {
      ...state,
      answers,
      attempts: newAttempts,
      latencyMs,
      firstTryCorrect: firstTry,
    };
    // Roll adaptive state forward (bucket, EWMA, damping, bonus gate).
    ns = { ...ns, ...recomputeAdaptive(ns) };
    return [
      ns,
      {
        correct: isCorrect,
        locked,
        attempt: priorAttempts + 1,
        correct_choice: locked ? correct : null,
      },
    ];
  }

  if (et === "advance_quiz") {
    // Ensure the upcoming transition sees the latest bucket.
    const staged = { ...state, ...recomputeAdaptive(state) };
    return nextMainOrBonusOrResult(staged, nowMs);
  }

  return [state, {}];
}

function computeScore(state) {
  const bonusAnswered = state.answers.filter((a) => BONUS_QUIZ_IDS.includes(a.qid)).length;
  const total = NUM_QUIZZES + (bonusAnswered > 0 ? BONUS_QUIZ_IDS.length : 0);
  const correct = state.answers.filter((a) => a.correct).length;
  const firstTry = state.answers.filter((a) => a.first_try_correct).length;
  return { correct, total, first_try: firstTry, answers: state.answers };
}

window.Reducer = {
  newState, reduce, computeScore,
  NUM_LESSONS, NUM_QUIZZES, BURN_IN_QUIZZES, BONUS_QUIZ_IDS, ANSWER_KEY,
};
