# Debate Tutor — pitch

> **One line:** a voice-first AI debate coach that makes you think by speaking — and it knows you.

## Problem

- People think best out loud, but nobody argues back. Social media is an
  echo chamber (you get blocked, not rebutted); ChatGPT agrees with you.
- Generic advice ("eat less, move more", "just be positive") fails because
  it doesn't know the person: their interests, their stakes, their style.
- Nobody teaches *how to argue* — evidence quality, steelmanning, spotting
  a weak claim — as a daily practice.

## Solution

A voice-first **debate coach**:

1. You pick a subject (9 starter subjects + free debate, or bring your own).
2. The coach opens with a stance. You make claims out loud — typed works too.
3. The coach pushes back with evidence, teaches the thinking inside every
   rebuttal, and scores your debate (score card after every turn: stance,
   counter-argument, one piece of evidence, next challenge).
4. **It knows you**: your interests and debate style (devil's advocate /
   Socratic / encouraging) are injected into every session — examples,
   stakes, and challenges bend toward you.

## Demo script (2–3 minutes)

1. **Setup (15s):** pick "Will AI Take Our Jobs?", depth Balanced, profile:
   interests = Tech & AI, style = Devil's advocate.
2. **Claim (30s):** say *"AI will replace teachers within five years."*
   → Coach counters with evidence (history of automation waves), score card
   lands at ~38, stance "Coach disagrees", "Your challenge" question shown.
3. **Adapt (30s):** answer with the taught fact — *"so it changes jobs
   instead of deleting them?"* → score climbs, green ▲, "Partly right".
4. **Personalization beat (30s):** coach references your tech interest and
   devil's-advocate style — *"since you're into AI, let's steelman the
   teachers' case…"*
5. **Voice (30s):** switch to hands-free, keep debating — coach speaks back,
   barge-in works, replay at 0.7×.

## Moat: personalization

- The learner profile shapes **every** debate — examples, counter-arguments,
  subject suggestions, challenge difficulty. Generic chatbots can't do this
  without a profile layer, and nobody else builds *debates*.
- Per-user debate corpus (claims, scores, misconceptions revealed) is a
  proprietary asset that compounds: the more you debate, the sharper the
  coach gets.
- Voice-first + multilingual (31 debate languages) + real rebuttal format is
  a hard bundle to copy: STT/TTS/realtime infrastructure + debate prompt
  engineering + scoring.

## Roadmap

- Subject library expansion + subject suggestions from your interests
- Memory across sessions (the coach remembers past debates)
- Clinician-reviewed / fact-checked subject tiers
- Group debates (debate the coach, then debate your friends)
- Profile portability + account sync
- Streaks and debate-skill analytics

## Numbers

- 31 debate languages · 28-language UI · 9 starter subjects + free debate
- ~270 backend tests, all green
- Stack: FastAPI + SQLite · React 18 + Vite (PWA) · DeepSeek · ElevenLabs +
  Edge-TTS · DashScope qwen realtime · Silero VAD
