import Waveform from './Waveform';
import DebateCard from './DebateCard';
import { useT } from '../i18n/useI18n';

const SPEEDS = [0.7, 1, 1.5];

/**
 * @param {object}   props
 * @param {object}   props.msg               - Message object (id, role, text, feedback, audio, streaming, pending, noSpeech, error_type, interrupted)
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
  const isModerator = msg.role === 'moderator';

  const feedback = msg.feedback || null;

  return (
    <div className={`msg ${isTutor ? 'msg-tutor' : (isModerator ? 'msg-moderator' : 'msg-user')}`}>
      <div className="msg-meta">
        {isTutor && (
          <span className="msg-avatar">
            <Waveform active={isPlaying} color="#FFFFFF" height={11} barWidth={1.5} gap={1.5} />
          </span>
        )}
        {isModerator && <span className="msg-avatar msg-avatar-moderator">⚖️</span>}
        <span>
          {isModerator
            ? t('bubble.moderator', 'moderator')
            : (isTutor ? t('bubble.tutor') : t('bubble.you'))}
        </span>
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

      </div>

      {/* Debate feedback card (attached to user messages, v13) */}
      {feedback && !msg.pending && !msg.noSpeech && (
        <DebateCard feedback={feedback} lang={lang} />
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
