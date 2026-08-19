# Think By Speaking — pitch

> **One line:** a voice-first AI debate coach that makes you think by speaking — it knows you, it remembers you, and it always answers back.

## Problem

- People think best out loud, but nobody argues back. Social media is an
  echo chamber (you get blocked, not rebutted); chatbots agree with you.
- **A huge population learns by listening, not reading** — the elderly,
  children, low-vision users, commuters, anyone screen-averse. For them,
  "read this article" is not learning; **speaking and being answered back is**.
- Generic advice fails because it doesn't know the person: their interests,
  their stakes, their style. And nothing measures *how well you argue* —
  the logic of your claims, the fallacies you lean on, how you deliver them.

## Solution

A voice-first **debate coach** that opens like a show: a host introduces the
motion, then a coach debates you — evidence, steelmanning, fallacy radar,
and a live score. Every turn comes back with a card:

- **What you said** — stance, running score, counter-argument, evidence
- **Fallacy radar** — strawman, false dilemma, ad hominem, red herring…
  flagged with your own words quoted
- **Structure** — one line on hook, flow, and evidence
- **How you sounded** — filler words (um/like), pace (words/sec), pitch
  (varied vs monotone)
- **Modes** — Socratic, Heckler, Boardroom, Devil's advocate, Encouraging

And it **remembers**: every debate feeds per-user analytics — score trends,
fallacy patterns, filler counts — visible on the Progress screen. The more
you debate, the sharper the coach gets.

## Demo script (2–3 minutes)

1. **Setup (20s):** pick "Will AI Take Our Jobs?", depth Balanced, style
   Heckler, profile: interests = Tech & AI. Voice: British male.
2. **The opening (15s):** the host speaks — *"Welcome to the debate floor…
   before I reveal any position of mine, I need yours."*
3. **Claim (30s):** say *"AI will replace teachers within five years."*
   → the coach counters with evidence (history of automation waves),
   score card lands at ~38, **fallacy radar flags the overclaim**, and the
   delivery chip counts your fillers.
4. **Adapt (30s):** answer with the taught fact — *"so it changes jobs
   instead of deleting them?"* → score climbs, "Partly right".
5. **Personalization beat (20s):** the coach references your tech interest
   and heckler mode — *"since you're into AI, let's steelman the teachers'
   case…"*
6. **Progress (10s):** the Progress screen shows your score trend and
   fallacy history across sessions — **persistent memory, the moat.**

## Moat

- **Personalization**: interests + debate style shape every session —
  examples, counter-arguments, challenges.
- **Persistent memory**: per-user debate analytics (scores, fallacies,
  fillers) accumulate across sessions — a proprietary corpus that
  compounds. Generic chatbots have none of it.
- **Delivery analysis**: filler/pace/pitch on the voice path — measuring
  *how* you speak, not just what you say.
- **The bundle**: voice-first + multilingual (31 debate languages) +
  real rebuttal format + a host/coach two-voice experience — hard to copy.

## Roadmap

- Voice-guided setup ("grandma mode": the host asks the questions)
- Subject library growth + interest-matched suggestions
- Group debates; clinician-reviewed subject tiers
- Guest device memory synced to accounts
- Streaks and skill analytics

## Numbers

- 31 debate languages · 28-language UI · 9 starter subjects + free debate
- ~290 backend tests, all green
- Stack: FastAPI + SQLite · React 18 + Vite (PWA) · DeepSeek · ElevenLabs +
  Edge-TTS · DashScope qwen realtime · Silero VAD
