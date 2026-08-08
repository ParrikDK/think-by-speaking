# Adaptive Learner-Led Tutoring — Design Spec

**Date:** 2026-08-03
**Target:** v8A (localhost:8002) — prompt-side change; STT is ElevenLabs Scribe v2

## 1. Problem

The beginner session is a fixed script. Every learner gets the same conveyor:
tutor models a word → learner repeats → tutor models the next word — regardless of
who the learner is, what they already know, or where the conversation goes
(live-observed 2026-08-03: 你好 → 你好吗 → 我很好 → 你呢 → 谢谢 → 不客气 → 再见).

The tutor feels like a lesson player, not a person standing there. The learner
never takes the floor, and nothing in the tutor's behavior responds to the
learner's actual production.

## 2. Goals

1. **Natural greeting opening** — the first message is a real greeting with one
   modeled word woven in, ending in a genuine question the learner can answer in
   either language. The learner's answer IS the placement probe — never spelled
   out, never a menu.
2. **Flexible adaptation, not classification** — the tutor meets the learner
   where they are every turn. No black/white "target-language → knows words /
   native-language → beginner" branching. An attempt at the target language is
   enthusiasm, not evidence — never assume prior knowledge from a single word.
3. **Same teaching density, responsive target** — still exactly 1-2 new words
   per turn, but chosen from the learner's thread, not a fixed sequence.
4. **Production, not parroting** — every turn ends with a question that forces
   the learner to USE words they've already met in a new combination. Never
   "can you repeat X?"
5. **Transcript-based pronunciation coaching** — Scribe's transcript is "what
   was heard." When the learner attempts a just-modeled phrase and the
   transcript comes back near-miss or garbled, the tutor coaches the sound.
   Applies to speech turns only (typed input carries no pronunciation signal).
6. **Spoken-only scenario suggestions** — once roughly a dozen words have
   accumulated, the tutor suggests real-life situations and role-plays them.
7. **Single-page onboarding** — native language, learning language, and
   difficulty level all on the first page (user-directed 2026-08-03,
   "like in v8b"). Replaces v8A's 5-step wizard
   (Welcome → Native → Target → Level → Scenario).

## 3. Design

### 3.1 The opening (beginner)

Replaces the current "introduce ONE word + invite them to repeat it" with a
natural greeting. Draft behavior:

> "Hi! I'm so happy you're here. I'm your Mandarin practice partner — 你好!
> That's 'hello'. So — how's your day going?"

- The modeled word appears inside the greeting itself (real use, not a lesson).
- The closing question is answerable in either language; the answer's language
  and content simply inform what the tutor does next — no branching script.
- Intermediate/fluent openings stay as-is (already greet in the target
  language + open question) — they gain the flexible-adaptation and
  production rules, not a new opening.

### 3.2 The turn loop (all levels, four beats)

1. **1-2 new words per turn** — density unchanged; selection follows the
   learner's thread (what they said, what they asked, where the moment leads).
2. **Acknowledge first** — name what the learner produced before adding
   anything; praise the attempt, not invented pronunciation quality.
3. **End with a production question** — a question only answerable by using
   words already met ("how would you ask me how I am?" → they must assemble
   你好吗). Never end with bare repeat-after-me.
4. **One step past what they proved** — if they produced in the target
   language, test the next increment (can they combine? can they vary?); if
   they produced in native, scaffold harder. Never a fixed next lesson.

### 3.3 Flexible adaptation principle (replaces any classification)

Persona rule, phrased as a principle, not a decision tree:

> Meet the learner where they are, every turn. Adapt your next step to what
> they just produced. If they attempt the target language, nurture that
> attempt and build on it — never assume prior knowledge from a single word;
> an attempt is enthusiasm, not evidence. If they answer in their native
> language, teach from the start. No fixed script, no assumptions locked in —
> flow like a person.

### 3.4 Transcript-based pronunciation coaching

**Signal:** the tutor just taught/modeled a specific phrase; the learner's
speech turn comes back from Scribe as a near-miss or garbled version. The
gap between *expected* (the teaching context) and *recognized* (the
transcript) is the pronunciation signal.

**Mechanics:**

- **Speech vs typed:** v8A already prefixes typed Chinese input with
  `[Typed]:` — the persona coaches pronunciation ONLY on non-typed turns.
  Typed input carries no pronunciation signal (the learner typed exact
  characters) — never coach it.
- **Proximity, not validity:** a learner saying something *valid but
  different* is a win — celebrate it. The flag is a close-but-wrong attempt:
  similar-sounding different word (Cantonese tone flips: 食→色), partial
  match, or nonsense near the modeled phrase.
- **Calibration (Scribe has its own noise):** one odd transcript → one gentle
  re-model ("let's try that again, slow it down"), never "you said it wrong."
  Only *repeated* near-misses for the same word across turns → targeted
  mini-drill on that word.
- **No romanization:** tone coaching uses 聲調 descriptions (first tone,
  flatter, shorter) — inside the existing no-romanization contract.
- **Never fabricate praise:** the persona must not claim pronunciation quality
  it cannot perceive from a correct transcript ("your pronunciation sounds
  great!") — praise the attempt and the content instead.

**Level tuning:** beginner — re-model once, celebrate effort; intermediate/
fluent — coach the sound more directly and consistently when the signal fires.

### 3.5 Scenario engine (spoken only)

- Trigger: the tutor's own judgment from history — roughly a dozen words
  taught across the session (self-monitored; the full conversation is in
  context every turn).
- Behavior: suggests a real-life situation built from the words actually
  learned ("you've got a nice toolkit — let's use it. Pretend I'm the cha
  chaan teng waiter…") and role-plays it for several turns.
- No UI surface. Spoken only. No threshold constant in code — prompt-side.

### 3.6 Onboarding consolidation (v8B-style single page)

Replace the 5-step wizard (`welcome` → `ob-native` → `ob-target` →
`ob-level` → `ob-scenario` screens) with ONE setup screen containing, top
to bottom:

- **Header** (from WelcomeScreen): UI-language select + auth buttons
  (login/logout/progress)
- **Native language** picker (the learner's mother tongue — v8B globe
  pattern or a compact select)
- **Learning language** grid (v8B `LanguagePicker` grid style)
- **Difficulty** pills (v8B `LevelSelector` style)
- **Scenario** optional chips (v8A still has scenarios — free talk
  default, collapsible section)
- English learners get the accent pills inline

Delete `WelcomeScreen`, `NativeLanguageStep`, `TargetLanguageStep`,
`LevelStep`, `ScenarioStep`, `StepDots`. App.jsx screens `welcome`,
`ob-native`, `ob-target`, `ob-level`, `ob-scenario` collapse into one
`setup` screen. `startChat({langObj, lvl, scenarioObj})` unchanged.

### 3.7 Guardrails (unchanged, now more important)

- Language-drift nudge (`_reply_language_mismatch` / `_nudge_retry`) — keep.
- `_strip_jyutping` defense-in-depth — keep.
- Silence handling / silence messages — keep.
- JSON contract (reply/translation/grammar, no-meta-text rule, no
  romanization) — **no new fields, no contract changes.**

## 4. Non-goals

- No schema/API changes; no new JSON contract fields.
- No scenario suggestion UI cards (spoken-only scenario suggestions — the
  onboarding consolidation is the only frontend change).
- No Scribe confidence-score extraction (future enhancement — would let the
  tutor suppress coaching when the transcript itself is unreliable).
- No actual audio-level pronunciation assessment (impossible from text).
- No scenarios removal: v8A keeps its scenario picker (folded into the
  single setup page as optional chips).

## 5. Companion change (user-approved)

Port the casual HK Cantonese register note from v8B (`_REGISTER_NOTES["yue"]`:
廣東話 not 粵語, casual spoken register, HK slang/particles) into v8A's
`_PERSONAS`, so v8A matches v8B's voice direction (v8B commit `86c0d62`).

## 6. File impact

- `backend/app/prompts/tutor.py` — persona template rewrites
  (beginner_init, beginner, intermediate, fluent) + register note + shared
  rule constants (_ADAPTATION_PRINCIPLE, _PRONUNCIATION_COACH,
  _SCENARIO_ENGINE) wired into `build_system_prompt`; `[Typed]:` prefix for
  typed Chinese input in `build_messages` (ported from v8B — v8A currently
  lacks it). Contract untouched.
- `backend/app/routers/chat.py` — `_nudge_retry` strips the `[Typed]:`
  prefix before the script-ratio re-check (v8B fix; prevents the prefix
  diluting the CJK ratio).
- `backend/tests/test_tutor_prompts.py`, `backend/tests/test_chat_api.py` —
  new tests (production rule, no-classification principle,
  pronunciation-coaching rule, [Typed]-awareness + nudge behavior, register
  note, greeting shape).
- `frontend/src/components/SetupScreen.jsx` (new) — single-page onboarding;
  delete WelcomeScreen, NativeLanguageStep, TargetLanguageStep, LevelStep,
  ScenarioStep, StepDots; rewire `frontend/src/App.jsx` (5 screens → 1).
- Live QA battery (per level, 4-turn conversations, logged) — the established
  v8A QA loop.

## 7. Testing strategy

1. Prompt-content tests for every new rule (each rule's distinctive wording
   asserted per level, including negative assertions where scoped, e.g.
   register note yue-only, typed-prefix languages).
2. Full suite green (207 baseline).
3. Frontend: `npm run build` clean + headless Playwright check of the
   single-page onboarding (all three selections visible; starting a session
   works end-to-end).
4. Live QA battery: per level (beginner/intermediate/fluent), 4 back-and-forth
   turns each, log responses, judge for: scripted-drift (still conveyor-like?),
   production questions present, adaptation to learner's language choice,
   pronunciation-coaching firing correctly on garbled transcripts, scenario
   suggestion appearing late in a long session.
