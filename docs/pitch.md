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

A voice-first **debate coach** that opens like a show with **three speakers**:
a neutral **moderator (the host)** frames the motion and keeps the debate
fair, a **coach** debates you — evidence, steelmanning, fallacy radar, and a
live score — and **you** speak your position.

- **Framing phase** — the moderator defines the topic and the rules; no
  scores until the debate actually starts, so your opening position
  statement earns no score
- **Moderator, on by default (toggle off anytime)** — every second turn the
  moderator interjects, reading out the score and asking a clarifying
  question; turn it off for a pure coach–you exchange
- **Every turn comes back with a card:**
  - **What you said** — stance, running score, counter-argument, evidence
  - **Fallacy radar** — strawman, false dilemma, ad hominem, red herring…
    flagged with your own words quoted
  - **Structure** — one line on hook, flow, and evidence
  - **How you sounded** — filler words (um/like), pace (words/sec), pitch
    (varied vs monotone)
  - **Modes** — Socratic, Heckler, Boardroom, Devil's advocate, Encouraging
- **Voice picker** — British male by default; switch the coach's voice anytime
- **Spoken session recap** — the moderator reads out your scores and
  takeaways when the debate ends
- **Voice-guided setup ("grandma mode")** — the moderator asks the setup
  questions out loud, so there's nothing to read
- **Guest device memory** — debates as a guest are remembered on the device,
  ready to sync to an account

And it **remembers**: every debate feeds per-user analytics — score trends,
fallacy patterns, filler counts — visible on the Progress screen. The more
you debate, the sharper the coach gets.

## Demo script (2–3 minutes)

1. **Setup (20s):** pick "Will AI Take Our Jobs?", depth Balanced, style
   Heckler, profile: interests = Tech & AI. Voice picker: British male
   (the default).
2. **Framing phase (20s):** the moderator sets the stage — *"Tonight's
   motion: 'AI will take our jobs.' You're speaking in favor. No scores
   until the debate starts — so give me your position, plainly."* You say
   *"AI will replace teachers within five years."* No score card yet — the
   opening position statement earns no score.
3. **Round one (25s):** the coach pushes back with evidence — the history
   of automation waves, from agriculture to manufacturing. Your first score
   card lands at ~38, the **fallacy radar flags the overclaim** with your
   own words quoted, and the delivery chip counts your fillers.
4. **Moderator, turn 2 (15s):** the moderator interjects, reading the score
   out loud — *"38 to you after round one. What makes teaching different
   from the waves we've survived before?"*
5. **Adapt (25s):** answer with the taught fact — *"so it changes jobs
   instead of deleting them?"* → the score climbs, "Partly right". The
   coach bends toward your profile — *"since you're into AI, let's steelman
   the teachers' case…"*
6. **Moderator, turn 4 (15s):** *"61 to you. One minute left — land your
   best point."*
7. **Recap (10s):** the debate ends — the moderator delivers a **spoken
   session recap** of your scores and takeaways, and the Progress screen
   shows your score trend and fallacy history across sessions —
   **persistent memory, the moat.**

## Moat

- **Personalization**: interests + debate style shape every session —
  examples, counter-arguments, challenges.
- **Persistent memory**: per-user debate analytics (scores, fallacies,
  fillers) accumulate across sessions — a proprietary corpus that
  compounds. Generic chatbots have none of it.
- **Delivery analysis**: filler/pace/pitch on the voice path — measuring
  *how* you speak, not just what you say.
- **The bundle**: voice-first + multilingual (31 debate languages) +
  real rebuttal format + a three-speaker moderator/coach experience —
  hard to copy.

## Roadmap

- Subject library growth + interest-matched suggestions
- Group debates; clinician-reviewed subject tiers
- Account sync for guest device memory
- Streaks and skill analytics

## Numbers

- 31 debate languages · 28-language UI · 9 starter subjects + free debate
- ~306 backend tests, all green
- Stack: FastAPI + SQLite · React 18 + Vite (PWA) · DeepSeek · ElevenLabs +
  Edge-TTS · DashScope qwen realtime · Silero VAD
