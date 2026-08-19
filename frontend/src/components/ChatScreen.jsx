import { useEffect, useRef, useCallback, useState } from 'react';
import MessageBubble from './MessageBubble';
import MicButton from './MicButton';
import VolumeMeter from './VolumeMeter';
import useSileroVAD, { preloadVadAssets } from '../hooks/useSileroVAD';
import { pickRecorderMime, recorderBlobType } from '../utils/recorder';
import useAudioPlayback from '../hooks/useAudioPlayback';
import { composeCardSpeech, speakHostLine } from './DebateCard';
import { useT } from '../i18n/useI18n';

export default function ChatScreen({
  lang,
  targetLang,
  level,
  messages,
  sending,
  onSendAudio,
  onSendText,
  onRegenerateAudio,
  onEndSession,
  onNewConversation,
  onNavigate,
  user,
}) {
  const t = useT(lang);
  const chatEndRef = useRef(null);
  const audioCtxRef = useRef(null);
  const bargeInRef = useRef(null);
  const endedRef = useRef(null);
  const recordAnalyserRef = useRef(null);
  const recordRAFRef = useRef(null);

  const [handsFree, setHandsFree] = useState(false);
  const [inputMode, setInputMode] = useState('voice'); // 'voice' | 'type'
  const [text, setText] = useState('');
  const [recording, setRecording] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [playingId, setPlayingId] = useState(null);
  const [manualVolume, setManualVolume] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [micError, setMicError] = useState(null);
  // v13.2 voice-first: auto-read each new feedback card with the host voice
  const [voiceFirst, setVoiceFirst] = useState(false);
  const wasVoiceFirstRef = useRef(false);
  const spokenFeedbackRef = useRef(new Set()); // message ids whose card was already read

  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const recordingRef = useRef(false); // ref-based guard for mic-toggle race (R4)

  const getAudioContext = useCallback(() => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    return audioCtxRef.current;
  }, []);

  const { play, stop: stopAudio, isPlaying, isBuffering } = useAudioPlayback({
    audioContext: null, // created lazily on first play
    onBargeIn: bargeInRef,
    onEnded: endedRef,
  });

  // ── Playback wiring (speed-aware) ──
  const handlePlay = useCallback((msgId, audio, rate) => {
    setPlayingId(msgId);
    play(audio, rate);
  }, [play]);

  const handleStopPlayback = useCallback(() => {
    stopAudio();
    setPlayingId(null);
  }, [stopAudio]);

  // v13.1: when the debater's reply finishes, speak the moderator's queued
  // line (the host voice) — the three speakers in order. Declared after
  // handlePlay (the deps array reads it at render time).
  const moderatorQueueRef = useRef([]);
  useEffect(() => {
    endedRef.current = () => {
      setPlayingId(null);
      const next = moderatorQueueRef.current.shift();
      if (next) handlePlay(next.id, next.audio, playbackSpeed);
    };
  }, [setPlayingId, handlePlay, playbackSpeed]);

  // Auto-play each new debater reply once it lands, using the user's speed
  // (v13.1: the moderator's line plays too — the host's voice — so the
  // three-speaker experience is actually SPOKEN on the typed path. The
  // moderator queues behind the debater's audio instead of cutting it).
  const autoPlayedRef = useRef(new Set());
  useEffect(() => {
    for (const m of messages) {
      if ((m.role === 'tutor' || m.role === 'moderator') && m.audio && !m.streaming && !autoPlayedRef.current.has(m.id)) {
        autoPlayedRef.current.add(m.id);
        if (m.role === 'moderator' && (isPlaying || isBuffering)) {
          moderatorQueueRef.current.push({ id: m.id, audio: m.audio });
        } else {
          handlePlay(m.id, m.audio, playbackSpeed);
        }
      }
    }
  }, [messages, handlePlay, playbackSpeed, isPlaying, isBuffering]);

  // ── v13.2 voice-first: read feedback cards with the host voice ──
  const speakCard = useCallback((feedback) => {
    const text = composeCardSpeech(feedback, t);
    if (!text) return;
    speakHostLine(text, lang, { stop: stopAudio, play });
  }, [t, lang, stopAudio, play]);

  // Only cards that ARRIVE while the toggle is on are auto-read — cards
  // already on screen when it flips on are marked as spoken so they don't
  // all read out at once.
  useEffect(() => {
    if (voiceFirst && !wasVoiceFirstRef.current) {
      const existing = new Set();
      for (const m of messages) {
        if (m.role === 'user' && m.feedback) existing.add(m.id);
      }
      spokenFeedbackRef.current = existing;
    }
    wasVoiceFirstRef.current = voiceFirst;
  }, [voiceFirst, messages]);

  // Speak each new feedback card once it lands. Delays until the tutor's
  // reply audio has finished: isBuffering/isPlaying are set synchronously
  // by useAudioPlayback, so a card that lands in the same commit as the
  // tutor audio (complete payload) waits for the reply — the read never
  // cuts the debater mid-sentence. A later tutor reply still barges an
  // in-flight read (shared useAudioPlayback instance).
  useEffect(() => {
    if (!voiceFirst || isPlaying || isBuffering) return;
    for (const m of messages) {
      if (m.role === 'user' && m.feedback && !spokenFeedbackRef.current.has(m.id)) {
        spokenFeedbackRef.current.add(m.id);
        speakCard(m.feedback);
      }
    }
  }, [messages, voiceFirst, isPlaying, isBuffering, speakCard]);

  // R3: VAD maxDurationReached recovery — toggle hands-free off/on to restart VAD
  const handleVADRestart = useCallback(() => {
    setHandsFree(false);
    setTimeout(() => setHandsFree(true), 150);
  }, []);
  const sendingRef = useRef(sending);
  sendingRef.current = sending;
  const sendAudioRef = useRef(onSendAudio);
  sendAudioRef.current = onSendAudio;

  const handleVADBlob = useCallback((blob) => {
    if (sendingRef.current) return;
    handleStopPlayback();
    sendAudioRef.current?.(blob);
  }, [handleStopPlayback]);

  const { isSpeaking, isRecording: isVADRecording, error: vadError, recordingDuration, maxDurationReached, volumeLevel, initializing, stage } = useSileroVAD({
    handsFree,
    audioContext: handsFree ? getAudioContext() : null,
    onAudioBlob: handleVADBlob,
    onBargeIn: bargeInRef,
    isPlaying,
  });

  // Warm the VAD model + WASM at page load so the first hands-free
  // activation is fast (iOS over the tunnel, 2026-08-03).
  useEffect(() => {
    preloadVadAssets();
  }, []);

  // ── Manual push-to-talk recording ──
  const startRecording = useCallback(async () => {
    if (recordingRef.current) return; // R4: prevent race on rapid mic-toggle
    recordingRef.current = true;
    handleStopPlayback();
    setConnecting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      streamRef.current = stream;

      // Set up volume analyser for push-to-talk feedback
      const ctx = getAudioContext();
      const srcNode = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      srcNode.connect(analyser);
      recordAnalyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      let lastUpdate = performance.now();
      (function tick(now) {
        if (!recordAnalyserRef.current) return;
        analyser.getByteTimeDomainData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const val = dataArray[i] / 128 - 1;
          sum += val * val;
        }
        const rms = Math.sqrt(sum / dataArray.length);
        const vol = Math.min(1, rms * 2.5);
        if (now - lastUpdate > 80) {
          setManualVolume(vol);
          lastUpdate = now;
        }
        recordRAFRef.current = requestAnimationFrame(tick);
      })(performance.now());

      const mimeType = pickRecorderMime();
      const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = mr;
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.start();
      setRecording(true);
    } catch (err) {
      console.error('Mic access failed:', err);
      setMicError(t('chat.mic_error', 'Microphone access denied.'));
      setTimeout(() => setMicError(null), 6000);
    } finally {
      setConnecting(false);
    }
  }, [handleStopPlayback, getAudioContext]);

  const stopRecording = useCallback(() => {
    recordingRef.current = false; // R4: clear guard before cleanup
    // Clean up volume analyser
    cancelAnimationFrame(recordRAFRef.current);
    if (recordAnalyserRef.current) {
      recordAnalyserRef.current.disconnect();
      recordAnalyserRef.current = null;
    }
    setManualVolume(0);

    const mr = mediaRecorderRef.current;
    const stream = streamRef.current;
    setRecording(false);
    if (mr && mr.state !== 'inactive') {
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorderBlobType(mr) });
        if (stream) stream.getTracks().forEach((tr) => tr.stop());
        streamRef.current = null;
        if (blob.size > 0 && !sendingRef.current) sendAudioRef.current?.(blob);
      };
      mr.stop();
    } else if (stream) {
      stream.getTracks().forEach((tr) => tr.stop());
      streamRef.current = null;
    }
  }, []);

  const handleMicToggle = useCallback(() => {
    if (handsFree || sendingRef.current) return; // VAD owns the mic in hands-free
    if (recordingRef.current) stopRecording();
    else startRecording();
  }, [handsFree, startRecording, stopRecording]);

  // Release mic on unmount
  useEffect(() => () => {
    cancelAnimationFrame(recordRAFRef.current);
    if (recordAnalyserRef.current) { recordAnalyserRef.current.disconnect(); recordAnalyserRef.current = null; }
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== 'inactive') mr.stop();
    if (streamRef.current) streamRef.current.getTracks().forEach((tr) => tr.stop());
  }, []);

  // Spacebar toggles the mic (voice mode only, not while typing)
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      if (e.code === 'Space' && inputMode === 'voice' && !handsFree) {
        e.preventDefault();
        handleMicToggle();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [inputMode, handsFree, handleMicToggle]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── Text input ──
  const submitText = useCallback(() => {
    const value = text.trim();
    if (!value || sendingRef.current) return;
    setText('');
    handleStopPlayback();
    onSendText(value);
  }, [text, onSendText, handleStopPlayback]);

  const langLabel = targetLang?.native_name || targetLang?.name || '';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Top bar — v8B-style brand: language native name + level subtitle */}
      <div className="topbar">
        <div className="topbar-brand">
          <div>
            <div className="brand-mini-name">{langLabel}</div>
            {level && <div className="topbar-sub">{t('level.' + level, level)}</div>}
          </div>
        </div>
        <span className="topbar-spacer" />
        <button
          className={`topbar-btn ${voiceFirst ? 'topbar-btn-active' : ''}`}
          onClick={() => setVoiceFirst((v) => !v)}
          aria-pressed={voiceFirst}
          title={t('chat.voice_first', 'Voice-first')}
        >
          🔊 {t('chat.voice_first', 'Voice-first')}
        </button>
        {user && (
          <>
            <button className="topbar-btn" onClick={() => onNavigate('history')}>{t('chat.history')}</button>
            <button className="topbar-btn" onClick={() => onNavigate('progress')}>{t('chat.progress')}</button>
          </>
        )}
        <button className="topbar-btn" onClick={onNewConversation} title={t('topbar.new_conversation', 'New conversation')}>
          {t('topbar.new_conversation', 'New conversation')}
        </button>
        <button className="topbar-btn topbar-btn-danger" onClick={onEndSession}>{t('chat.end_session')}</button>
      </div>

      {/* Scenario banner */}
      {/* Messages */}
      <div className="msg-list">
        {messages.length === 0 ? (
          <div className="empty-state" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <p>{t('chat.empty_conversation', 'Your conversation will appear here.')}</p>
          </div>
        ) : (
          messages.map((m) => (
            <MessageBubble
              key={m.id}
              msg={m}
              lang={lang}
              isPlaying={playingId === m.id}
              speed={playbackSpeed}
              onSpeedChange={setPlaybackSpeed}
              onPlay={(rate) => handlePlay(m.id, m.audio, rate)}
              onStop={handleStopPlayback}
              onRegenerateAudio={(text) => onRegenerateAudio?.(m.id, text)}
            />
          ))
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Input dock */}
      <div className="chat-dock">
        {inputMode === 'voice' ? (
          <MicButton
            lang={lang}
            recording={recording}
            onToggle={handleMicToggle}
            disabled={sending}
            connecting={connecting}
            handsFree={handsFree}
            isSpeaking={isSpeaking}
          />
        ) : (
          <div className="chat-dock-row">
            <MicButton
              lang={lang}
              small
              recording={recording}
              onToggle={handleMicToggle}
              disabled={sending}
              connecting={connecting}
              handsFree={handsFree}
              isSpeaking={isSpeaking}
            />
            <input
              className="chat-text-input"
              type="text"
              value={text}
              placeholder={t('chat.type_placeholder')}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submitText(); }}
              disabled={sending}
              autoFocus
            />
            <button
              className="chat-send-btn"
              onClick={submitText}
              disabled={sending || !text.trim()}
              aria-label={t('chat.send')}
              title={t('chat.send')}
            >
              ➤
            </button>
          </div>
        )}

        <div className="mic-toggle-row">
          <button
            className={inputMode === 'type' ? 'pill-toggle pill-toggle-active' : 'pill-toggle'}
            onClick={() => setInputMode(inputMode === 'type' ? 'voice' : 'type')}
            aria-pressed={inputMode === 'type'}
            title={t('chat.typing_mode')}
          >
            ⌨️ {t('chat.typing_mode')}
          </button>
          <button
            className={handsFree ? 'pill-toggle pill-toggle-active' : 'pill-toggle'}
            onClick={() => {
              if (!handsFree) {
                // iOS Safari: AudioContext.resume() is only honored INSIDE a
                // user gesture. The VAD effect's resume runs after awaits
                // (model + mic), so it silently fails on iPhone and hands-free
                // hears nothing. Resume here, synchronously in the click.
                const ctx = getAudioContext();
                if (ctx.state === 'suspended') ctx.resume();
              }
              setHandsFree(!handsFree);
            }}
            aria-pressed={handsFree}
          >
            🎙️ {t('chat.hands_free')}
          </button>
          {(handsFree || recording) && (
            <span className="vad-status-wrap">
              <VolumeMeter volume={handsFree ? volumeLevel : manualVolume} />
              {handsFree && maxDurationReached ? (
                <button className="vad-restart-btn" onClick={handleVADRestart} title={t('chat.restart_mic', 'Restart microphone')}>
                  🔄 {t('chat.restart_mic', 'Restart mic')}
                </button>
              ) : (
                <span className={
                  vadError ? 'vad-status vad-status-error'
                    : (handsFree && isVADRecording) || recording ? 'vad-status vad-status-active'
                    : 'vad-status vad-status-init'
                }>
                  {vadError
                    ? `${t('chat.vad_error', 'Mic')}: ${vadError}`
                    : handsFree && initializing
                      ? `${t('chat.starting_mic', 'Starting mic…')} ${stage ? `[${stage}]` : ''}${stage === 'creating VAD' || stage === 'loading VAD' ? ` ${t('chat.first_time_model', '(first time: downloading voice model)')}` : ''}`
                      : recording
                        ? t('mic.listening')
                        : isVADRecording
                          ? (isSpeaking
                              ? t('chat.listening')
                              : `${t('chat.processing')} ${Math.floor(recordingDuration / 60000)}:${String(Math.floor((recordingDuration % 60000) / 1000)).padStart(2, '0')}`)
                          : ''}
                </span>
              )}
            </span>
          )}
        </div>
        {micError && <div className="mic-error" style={{ color: 'var(--color-pen)', fontSize: 12, textAlign: 'center', padding: '2px 0' }}>{micError}</div>}
      </div>
    </div>
  );
}
