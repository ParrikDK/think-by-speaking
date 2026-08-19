import { useCallback } from 'react';
import useAudioPlayback from '../hooks/useAudioPlayback';
import { hostLine } from '../api';
import { useT } from '../i18n/useI18n';

// ── Card speech (v13.2, voice-first) ───────────────────────────────
// One card read at a time, app-wide: every read — the "Read my card"
// button AND the voice-first auto-reads from both screens — registers its
// stop() here, so starting a new read stops the previous one (the same
// barge-in useAudioPlayback gives within a single instance).
let activeCardReadStop = null;

/** Stop whatever card read is currently playing (if any). */
export function stopCardRead() {
  if (activeCardReadStop) {
    const stop = activeCardReadStop;
    activeCardReadStop = null;
    stop();
  }
}

/**
 * Compose the spoken read-out of a feedback card in the UI language,
 * joining only the non-empty parts:
 * "Score 53. Debater disagrees. Debater's rebuttal: …. The evidence: …. Your challenge: …"
 */
export function composeCardSpeech(feedback, t) {
  if (!feedback) return '';
  const parts = [];
  parts.push(`${t('debate.score', 'Score')} ${Number(feedback.score) || 50}`);
  parts.push(t('debate.stance.' + feedback.stance, feedback.stance));
  if (feedback.counter) parts.push(`${t('debate.counter', "Debater's rebuttal")}: ${feedback.counter}`);
  if (feedback.evidence) parts.push(`${t('debate.evidence', 'The evidence')}: ${feedback.evidence}`);
  if (feedback.next) parts.push(`${t('debate.next', 'Your challenge')}: ${feedback.next}`);
  return parts.join('. ');
}

/**
 * Speak `text` with the HOST voice (POST /api/setup/host → {audio_base64})
 * and play it through the caller's useAudioPlayback. Any previous card
 * read is cut first. TTS failures are logged and swallowed — a failed
 * read-out must never break the screen.
 */
export async function speakHostLine(text, lang, { stop, play }) {
  if (!text) return;
  stopCardRead();
  try {
    const { audio_base64 } = await hostLine(text, lang);
    activeCardReadStop = stop; // we are now the active read
    play(audio_base64);
  } catch (e) {
    console.error('Card TTS failed:', e);
  }
}

/**
 * Post-turn debate feedback card (v13). Attached to USER messages: the
 * debater's stance on the claim, the running debate score with delta, the
 * counter-argument, one evidence-backed fact, the next challenge — plus
 * the Think By Speaking pillars (v13.1): fallacy radar chips, structure line and
 * the filler count.
 *
 * @param {object} feedback - {stance, score, score_delta, counter, evidence,
 *                            next, fallacies, structure, filler_count}
 * @param {string} lang     - UI language code
 */
export default function DebateCard({ feedback, lang }) {
  const t = useT(lang);
  const { play, stop, isPlaying, isBuffering } = useAudioPlayback({});
  const reading = isPlaying || isBuffering;

  const speak = useCallback(() => {
    speakHostLine(composeCardSpeech(feedback, t), lang, { stop, play });
  }, [feedback, t, lang, stop, play]);

  if (!feedback) return null;

  const { stance, score, score_delta, counter, evidence, next, fallacies, structure, filler_count, delivery } = feedback;
  const delta = Number(score_delta) || 0;
  const deltaClass = delta > 0 ? 'debate-delta-up' : delta < 0 ? 'debate-delta-down' : 'debate-delta-flat';
  const deltaArrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '±';
  const fallaciesList = Array.isArray(fallacies) ? fallacies.filter((f) => f && f.type) : [];
  const fillers = Number(filler_count) || 0;
  const pace = delivery?.pace ? `${t('debate.pace', 'Pace')}: ${delivery.pace} w/s` : null;
  const pitch = delivery?.pitch
    ? `${t('debate.pitch', 'Pitch')}: ${t('debate.pitch.' + delivery.pitch, delivery.pitch)}`
    : null;

  return (
    <div className="debate-card">
      <div className="debate-card-head">
        <div className="debate-score">
          <span className="debate-score-num">{Number(score) || 50}</span>
          <span className={`debate-delta ${deltaClass}`}>
            {deltaArrow} {delta !== 0 ? Math.abs(delta) : '0'}
          </span>
        </div>
        <span className={`debate-stance debate-stance-${stance}`}>
          {t('debate.stance.' + stance, stance)}
        </span>
      </div>

      {/* Fallacy radar */}
      {fallaciesList.length > 0 && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.fallacies', 'Fallacies')}</span>
          <div className="debate-fallacies">
            {fallaciesList.map((f, i) => (
              <span
                key={i}
                className="debate-fallacy"
                title={f.quote ? `${f.quote} — ${f.note || ''}` : (f.note || '')}
              >
                ⚠️ {t('debate.fallacy.' + f.type, f.type.replace(/_/g, ' '))}
                {f.note ? <span className="debate-fallacy-note"> {f.note}</span> : null}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Delivery chips: fillers + pace + pitch + structure */}
      {(fillers > 0 || pace || pitch || structure) && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.delivery', 'Delivery')}</span>
          <div className="debate-fallacies">
            {fillers > 0 && (
              <span className="debate-fallacy debate-fallacy-delivery">
                🎙️ {fillers} {t('debate.fillers', 'fillers')}
              </span>
            )}
            {pace && <span className="debate-fallacy debate-fallacy-delivery">⏱️ {pace}</span>}
            {pitch && <span className="debate-fallacy debate-fallacy-delivery">🎵 {pitch}</span>}
            {structure && <span className="debate-fallacy debate-fallacy-delivery">{structure}</span>}
          </div>
        </div>
      )}

      {counter && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.counter', "Debater's rebuttal")}</span>
          <span className="debate-text">{counter}</span>
        </div>
      )}
      {evidence && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.evidence', 'The evidence')}</span>
          <span className="debate-text">{evidence}</span>
        </div>
      )}
      {next && (
        <div className="debate-row debate-row-next">
          <span className="debate-label">{t('debate.next', 'Your challenge')}</span>
          <span className="debate-text">{next}</span>
        </div>
      )}

      {/* v13.2 voice-first: read the whole card aloud with the host voice */}
      <button
        type="button"
        className="debate-read-btn"
        onClick={speak}
        disabled={reading}
        title={t('debate.read_card', 'Read my card')}
      >
        {reading ? '…' : '🔊'} {t('debate.read_card', 'Read my card')}
      </button>
    </div>
  );
}
