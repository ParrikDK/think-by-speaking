import { useState } from 'react';
import Waveform from './Waveform';
import { useT } from '../i18n/useI18n';

// ── Word-level diff for grammar strike/insert rendering ──
// Tokenize into CJK chars (no spaces), Latin word-runs (incl. contractions
// like "l'amour") and whitespace — so a Latin word never gets diffed
// character-by-character against a similar word in the correction.
const CJK_RE = /[぀-ヿ㐀-䶿一-鿿가-힯]/;

function tokenize(s) {
  return s.match(/[぀-ヿ㐀-䶿一-鿿가-힯]|[A-Za-z0-9'()]+|\s+/g) || [];
}

function diffTokens(a, b) {
  const m = a.length;
  const n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const segs = [];
  let i = 0;
  let j = 0;
  let mode = null;
  let buf = '';
  const flush = () => {
    if (buf) segs.push({ type: mode, text: buf });
    buf = '';
  };
  const push = (nextMode, ch) => {
    if (mode !== nextMode) { flush(); mode = nextMode; }
    buf += ch;
  };
  while (i < m && j < n) {
    if (a[i] === b[j]) { push('same', a[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push('strike', a[i]); i++; }
    else { push('insert', b[j]); j++; }
  }
  while (i < m) push('strike', a[i++]);
  while (j < n) push('insert', b[j++]);
  flush();
  return segs;
}

function DiffText({ original, corrected }) {
  const segs = diffTokens(tokenize(original || ''), tokenize(corrected || ''));
  return (
    <span>
      {segs.map((seg, i) => {
        if (seg.type === 'strike') return <span key={i} className="diff-strike">{seg.text}</span>;
        if (seg.type === 'insert') return <span key={i} className="diff-insert">{seg.text}</span>;
        return <span key={i}>{seg.text}</span>;
      })}
    </span>
  );
}

const SPEEDS = [0.7, 1, 1.5];

/**
 * @param {object}   props
 * @param {object}   props.msg               - Message object (id, role, text, translation, grammar, audio, streaming, pending, noSpeech, error_type, interrupted)
 * @param {string}   props.lang              - User's UI language code
 * @param {(rate: number) => void} props.onPlay - Play audio at given speed
 * @param {() => void} props.onStop          - Stop audio playback
 * @param {boolean}  [props.isPlaying]       - Whether this message is currently playing
 * @param {number}   [props.speed]           - Playback speed multiplier
 * @param {(speed: number) => void} [props.onSpeedChange] - Speed change callback
 * @param {(text: string) => void} [props.onRegenerateAudio] - Regenerate TTS for given text
 */
export default function MessageBubble({ msg, lang, onPlay, onStop, isPlaying = false, speed = 1, onSpeedChange, onRegenerateAudio }) {
  const t = useT(lang);
  const isTutor = msg.role === 'tutor';
  const [showTranslation, setShowTranslation] = useState(true);

  const grammar = msg.grammar || null;

  return (
    <div className={isTutor ? 'msg msg-tutor' : 'msg msg-user'}>
      <div className="msg-meta">
        {isTutor && (
          <span className="msg-avatar">
            <Waveform active={isPlaying} color="#FFFFFF" height={11} barWidth={1.5} gap={1.5} />
          </span>
        )}
        <span>{isTutor ? t('bubble.tutor') : t('bubble.you')}</span>
      </div>

      <div className="msg-card">
        <div className="msg-text">
          {msg.pending ? (
            <span className="msg-text-pending">…</span>
          ) : msg.noSpeech ? (
            <span className="msg-no-speech">{t('chat.no_speech')}</span>
          ) : (
            <>
              {msg.error_type === 'llm_failure' && (
                <span className="msg-system-glitch">⚙️ {t('chat.system_glitch', 'System glitch')}: </span>
              )}
              {msg.error_type === 'tts_failure' && (
                <span className="msg-system-glitch">🔊 {t('chat.audio_failed', 'Audio unavailable')}: </span>
              )}
              {msg.text}
              {msg.streaming && <span className="stream-cursor" />}
              {msg.interrupted && (
                <span className="msg-interrupted"> ⚠️ {t('chat.interrupted', 'Interrupted')}</span>
              )}
            </>
          )}
        </div>

        {/* Pronunciation (pinyin/jyutping) below every message */}
        {msg.pronunciation && !msg.streaming && (
          <div className="msg-pronunciation">{msg.pronunciation}</div>
        )}

        {/* Translation (native language) — same placement as the
            pronunciation line, with a show/hide toggle */}
        {msg.translation && !msg.streaming && (
          <>
            <button
              type="button"
              className="msg-translation-toggle"
              onClick={() => setShowTranslation((v) => !v)}
            >
              {showTranslation
                ? t('chat.hide_translation', 'Hide translation')
                : t('chat.show_translation', 'Show translation')}
            </button>
            {showTranslation && <div className="msg-translation">{msg.translation}</div>}
          </>
        )}
      </div>

      {/* Grammar card (attached to user messages) */}
      {grammar && !msg.pending && !msg.noSpeech && (
        grammar.is_correct ? (
          <div className="grammar-card grammar-card-good">
            <div className="grammar-card-label">✓ {t('grammar.well_done')}</div>
            {grammar.explanation && <div className="grammar-explanation">{grammar.explanation}</div>}
          </div>
        ) : (
          <div className="grammar-card">
            <div className="grammar-card-label">✏️ {t('grammar.correction')}</div>
            <div>
              <DiffText original={msg.text} corrected={grammar.corrected_text} />
            </div>
            {grammar.explanation && <div className="grammar-explanation">{grammar.explanation}</div>}
          </div>
        )
      )}

      {/* Audio controls with working speed control */}
      {isTutor && msg.audio && !msg.streaming && (
        <div className="audio-controls">
          {SPEEDS.map((s) => (
            <button
              key={s}
              className={isPlaying && speed === s ? 'speed-btn speed-btn-active' : 'speed-btn'}
              onClick={() => { onSpeedChange?.(s); onPlay?.(s); }}
            >
              {t(`bubble.speed_${String(s).replace('.', '-') }x`, `${s}x`)}
            </button>
          ))}
          {isPlaying && (
            <button className="speed-btn speed-btn-stop" onClick={onStop}>{t('bubble.stop', '⏹')}</button>
          )}
        </div>
      )}

      {/* Retry TTS for audio-less tutor messages */}
      {isTutor && !msg.audio && !msg.streaming && msg.text && !msg.pending && (
        <div className="audio-controls">
          <button className="speed-btn" onClick={() => onRegenerateAudio?.(msg.text)}>
            🔊 {t('bubble.retry_audio', 'Generate audio')}
          </button>
        </div>
      )}
    </div>
  );
}
