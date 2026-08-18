import { memo, useEffect, useRef, useState } from 'react';
import useRealtime from '../hooks/useRealtime';
import DebateCard from './DebateCard';
import { useT } from '../i18n/useI18n';
import './RealtimeChatScreen.css';

// Realtime voice chat screen (v11 M2, 2026-08-08) — the post-design-review
// spike UI in React. Language/level/scenario come from Setup (no header
// chips in-app); the header keeps only the hands-free toggle and End.
// Dock order is the spike's thumb-zone stack: type row → meter → status →
// mic. All audio/WS behavior lives in useRealtime; this file is DOM wiring
// and rendering.

// lang attribute for target-language text (spike's LANG_TAG generalized).
function langTagFor(code) {
  if (code === 'yue' || code === 'zh-TW') return 'zh-Hant';
  if (code === 'zh') return 'zh-Hans';
  return code || 'en';
}

// First-line starter chip in the target language (the spike's 「早晨！」,
// generalized). Fallback "Hello!" — chip hidden when it duplicates chip 1.
const STARTER_GREETINGS = {
  yue: '早晨！', zh: '你好！', 'zh-TW': '你好！', en: 'Hello!', es: '¡Hola!',
  fr: 'Bonjour !', de: 'Hallo!', it: 'Ciao!', ru: 'Привет!', ko: '안녕!',
  vi: 'Xin chào!', id: 'Halo!', nl: 'Hallo!', pl: 'Cześć!', fil: 'Kumusta!',
  ms: 'Hai!', ja: 'こんにちは！', pt: 'Olá!', ar: 'مرحبا!', hi: 'नमस्ते!',
  th: 'สวัสดี!', tr: 'Merhaba!', sv: 'Hej!', he: 'שלום!',
  ur: 'السلام علیکم!', cs: 'Ahoj!',
};

// One chat bubble. Memoized — the mic meter re-renders the screen at
// ~12 Hz while recording, and bubbles must not re-render with it.
const RtBubble = memo(function RtBubble({ msg, lang, speaking, langTag, t, onReplay }) {
  const isTutor = msg.role === 'tutor';
  return (
    <div className={`rt-msg ${isTutor ? 'rt-msg-tutor' : 'rt-msg-user'}`} lang={langTag}>
      <span className="rt-who">{isTutor ? t('bubble.tutor') : t('bubble.you')}</span>
      {msg.unclear ? (
        // Wrong-script ASR misfire — the tutor understood the audio fine;
        // only the transcript was garbage.
        <div className="rt-unclear">{t('rt.unclear_transcript')}</div>
      ) : (
        <div>{msg.text}</div>
      )}
      {isTutor && speaking && (
        <span className="rt-eq" aria-hidden="true"><i /><i /><i /></span>
      )}
      {isTutor && msg.replay && (
        <button type="button" className="rt-replay" onClick={() => onReplay(msg.id)}>
          {t('bubble.replay')}
        </button>
      )}
      {/* Debate feedback card (v13): full-bleed inside the user bubble
          (2026-08-07 design review — no box-in-box). When the judge could
          not extract a claim, show the light ack instead of an empty card. */}
      {msg.feedback && (
        msg.feedback.counter || msg.feedback.evidence ? (
          <DebateCard feedback={msg.feedback} lang={lang} />
        ) : (
          <div className="rt-gcard rt-gcard-ok">✓ {t('debate.ack', 'Good claim — nothing to rebut.')}</div>
        )
      )}
    </div>
  );
});

export default function RealtimeChatScreen({
  lang,
  targetLang,
  level,
  scenario,
  nativeLang,
  profile,
  onEndSession,
  onLoginRequest,
}) {
  const t = useT(lang);
  const rt = useRealtime({
    lang: targetLang.code,
    level: level || 'beginner',
    scenarioId: scenario?.id || '',
    native: nativeLang?.code || 'en',
    profile,
  });
  const { mode, pttDown, pttRelease, pttSetCancel } = rt;

  const [typed, setTyped] = useState('');
  const chatRef = useRef(null);

  const langTag = langTagFor(targetLang.code);
  const langLabel = targetLang.native_name || targetLang.name || '';

  // Auto-scroll to the newest bubble on ANY message-content change. The
  // old length+last-text deps missed content landing on non-last messages
  // (the ASR user bubble is spliced BEFORE the in-flight tutor bubble, and
  // debate feedback cards arrive after the turn) - those grew the
  // list without triggering a scroll. Always pins to bottom, per the user
  // (2026-08-17: "keep it bottom most automatically").
  const msgsSig = rt.messages.map(
    (m) => `${m.text}|${m.feedback ? JSON.stringify(m.feedback) : ''}|${m.unclear}`
  ).join('||');
  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgsSig, rt.quotaCard]);

  // Window-level PTT listeners: release anywhere ends the hold; spacebar is
  // hold-to-talk on desktop (skipped while typing — activeElement check).
  useEffect(() => {
    const onUp = () => pttRelease();
    const onCancel = () => { pttSetCancel(true); pttRelease(); };
    const onKeyDown = (e) => {
      if (mode !== 'ptt' || e.code !== 'Space' || e.repeat) return;
      const a = document.activeElement;
      if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'BUTTON')) return;
      e.preventDefault();
      pttDown();
    };
    const onKeyUp = (e) => {
      if (mode !== 'ptt' || e.code !== 'Space') return;
      e.preventDefault();
      pttRelease();
    };
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [mode, pttDown, pttRelease, pttSetCancel]);

  // Mic button visuals (the spike's renderState): idle before the session,
  // filled "live" while connected, darker while recording, stop glyph while
  // the tutor speaks.
  const speakingState = rt.sessionActive && rt.wsOpen && rt.tutorSpeaking;
  const micClass = ['rt-mic'];
  if (rt.pttHeld) micClass.push('rt-mic-recording');
  else if (!rt.sessionActive) micClass.push('rt-mic-idle');
  else if (speakingState) micClass.push('rt-mic-speaking');
  else micClass.push('rt-mic-live');

  let micAria;
  if (rt.pttHeld) micAria = t('rt.release_to_send');
  else if (speakingState) micAria = t('rt.interrupt');
  else if (rt.sessionActive) micAria = mode === 'ptt' ? t('rt.hold_to_talk') : t('rt.end');
  else micAria = mode === 'ptt' ? t('rt.hold_to_talk') : t('rt.tap_to_start');

  let status;
  if (rt.pttHeld) status = rt.pttCancel ? t('rt.release_to_cancel') : t('rt.release_to_send');
  else if (!rt.sessionActive) status = mode === 'ptt' ? t('rt.hold_to_talk') : t('rt.tap_to_start');
  else if (rt.wsOpen && rt.tutorSpeaking) status = t('rt.tutor_speaking');
  else if (!rt.wsOpen) status = rt.reconnecting ? t('rt.reconnecting') : t('rt.connecting');
  else status = mode === 'ptt' ? t('rt.hold_to_talk') : t('rt.listening');

  // In ptt the mic is press-and-hold (click does nothing); in hands-free a
  // tap starts the session / interrupts the tutor / ends the session.
  const onMicClick = () => {
    if (mode === 'ptt') return;
    if (!rt.sessionActive) rt.start();
    else if (rt.tutorSpeaking) rt.interrupt();
    else rt.end();
  };

  const submitTyped = () => {
    const value = typed.trim();
    if (!value) return;
    setTyped('');
    rt.sendText(value);
  };

  const greeting = STARTER_GREETINGS[targetLang.code] || 'Hello!';

  return (
    <div className="rt-screen">
      <div className="topbar">
        <div className="topbar-brand">
          <div>
            <div className="brand-mini-name">{langLabel}</div>
            {level && <div className="topbar-sub">{t('level.' + level, level)}</div>}
          </div>
        </div>
        <span className="topbar-spacer" />
        <button
          type="button"
          className={`rt-mini ${mode === 'handsfree' ? 'rt-mini-active' : ''}`}
          aria-pressed={mode === 'handsfree'}
          title={t('rt.hands_free')}
          onClick={() => rt.setMode(mode === 'ptt' ? 'handsfree' : 'ptt')}
        >
          {t('rt.hands_free')}
        </button>
        <button
          type="button"
          className="topbar-btn topbar-btn-danger"
          onClick={() => { rt.end(); onEndSession(); }}
        >
          {t('rt.end')}
        </button>
      </div>

      {rt.banner && (
        <div className="rt-banner" role="alert">{t(rt.banner, rt.banner)}</div>
      )}

      <main className="rt-chat" ref={chatRef} aria-live="polite">
        {rt.messages.length === 0 && !rt.quotaCard && (
          <div className="rt-empty">
            <div className="rt-empty-big">{t('rt.say_hello')}</div>
            <div className="rt-empty-hint">
              {t(mode === 'ptt' ? 'rt.empty_hint_ptt' : 'rt.empty_hint_handsfree')}
            </div>
            <div className="rt-starters">
              <span className="rt-starter-lbl">{t('rt.starter_label')}</span>
              <button type="button" className="rt-chip" onClick={() => rt.sendText('Hello!')}>
                "Hello!"
              </button>
              {greeting !== 'Hello!' && (
                <button type="button" className="rt-chip" lang={langTag} onClick={() => rt.sendText(greeting)}>
                  「{greeting}」
                </button>
              )}
            </div>
          </div>
        )}

        {rt.messages.map((m) => (
          <RtBubble
            key={m.id}
            msg={m}
            lang={lang}
            langTag={langTag}
            t={t}
            speaking={rt.tutorSpeaking && m.id === rt.activeTutorId}
            onReplay={rt.replay}
          />
        ))}

        {/* Quota/trial card (close 4001 / proxy.quota_exhausted): guests get
            the register upsell, users the come-back-tomorrow note. */}
        {rt.quotaCard && (
          <div className="rt-quota">
            <div className="rt-quota-text">
              {t(rt.quotaCard === 'guest' ? 'rt.trial_ended' : 'rt.quota_ended')}
            </div>
            {rt.quotaCard === 'guest' && (
              <button type="button" className="rt-chip rt-quota-cta" onClick={onLoginRequest}>
                {t('login.create_account')}
              </button>
            )}
          </div>
        )}
      </main>

      <div className="rt-dock">
        <div className="rt-type-row">
          <input
            type="text"
            className="rt-type-input"
            value={typed}
            placeholder={t('rt.typed_placeholder')}
            aria-label={t('rt.typed_placeholder')}
            autoComplete="off"
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submitTyped(); }}
          />
          <button type="button" className="rt-send" onClick={submitTyped}>
            {t('chat.send')}
          </button>
        </div>
        <div className="rt-meter" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} className={rt.micLevel > (i + 1) / 6 ? 'rt-on' : ''} />
          ))}
        </div>
        <div className="rt-status-row">
          <div className="rt-status">{status}</div>
        </div>
        <button
          type="button"
          className={micClass.join(' ')}
          aria-label={micAria}
          onClick={onMicClick}
          onPointerDown={(e) => {
            if (mode !== 'ptt') return;
            e.preventDefault();
            e.currentTarget.blur(); // so Space doesn't re-click it
            pttDown();
          }}
          onPointerLeave={() => { if (mode === 'ptt') pttSetCancel(true); }}
          onPointerEnter={() => { if (mode === 'ptt') pttSetCancel(false); }}
        >
          <span className="rt-ring" />
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
               style={speakingState ? { display: 'none' } : undefined}>
            <rect x="9" y="2.5" width="6" height="11" rx="3" />
            <path d="M5.5 10.5a6.5 6.5 0 0 0 13 0" />
            <line x1="12" y1="17.5" x2="12" y2="21" />
            <line x1="9" y1="21" x2="15" y2="21" />
          </svg>
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"
               style={speakingState ? undefined : { display: 'none' }}>
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        </button>
      </div>

      {rt.latency.length > 0 && (
        <details className="rt-debug">
          <summary>Debug</summary>
          <h2>Latency per turn (speech end → first audio)</h2>
          {rt.latency.map((entry) => <div key={entry.id}>{entry.text}</div>)}
        </details>
      )}
    </div>
  );
}
