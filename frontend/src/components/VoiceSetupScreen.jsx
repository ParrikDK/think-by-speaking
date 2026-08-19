import { useCallback, useEffect, useRef, useState } from 'react';
import { hostLine, setupVoiceParse } from '../api';
import useAudioPlayback from '../hooks/useAudioPlayback';
import { useT } from '../i18n/useI18n';
import { startRecorder } from '../utils/capture';
import { pickRecorderMime } from '../utils/recorder';

/**
 * Voice-guided setup (v13.1, "grandma mode" v1) — the host speaks numbered
 * menus, the learner answers by voice, STT + LLM map the answer.
 * Research-informed (2026-08-19): numbered verbal options, beep-then-speak,
 * plain language, error-tolerant retries.
 */
const STEPS = ['subject', 'depth', 'style'];

const QUESTIONS = {
  subject:
    "Welcome! Let's set up your debate by voice. Say the subject you'd like to debate — for example, AI jobs, social media, remote work, or say free debate.",
  depth:
    "How deep should we go? Say one for Basics, two for Balanced, or three for Expert.",
  style:
    "How should I push back? Say one for Devil's advocate, two for Socratic, three for Heckler, four for Boardroom, or five for Encouraging.",
  retry: "I didn't quite catch that. Say the number, like one or two, or repeat the subject name.",
  done: 'All set. Starting your debate now.',
};

export default function VoiceSetupScreen({ scenarios, onBack, onStart }) {
  const t = useT('en');
  const [stepIdx, setStepIdx] = useState(0);
  const [answers, setAnswers] = useState({});
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false); // parsing / host talking
  const [retries, setRetries] = useState(0);
  const [status, setStatus] = useState('');
  const recorderRef = useRef(null);
  const { play } = useAudioPlayback();
  const [hostAudio, setHostAudio] = useState({}); // question -> base64 (prefetched)

  // Prefetch all static host lines once at mount (efficiency review:
  // no per-step TTS round trips).
  useEffect(() => {
    let cancelled = false;
    Promise.all(Object.entries(QUESTIONS).map(async ([key, text]) => {
      try {
        const { audio_base64 } = await hostLine(text);
        return [key, audio_base64];
      } catch {
        return [key, null];
      }
    })).then((pairs) => {
      if (!cancelled) setHostAudio(Object.fromEntries(pairs));
    });
    return () => { cancelled = true; };
  }, []);

  const say = useCallback(async (key) => {
    const b64 = hostAudio[key];
    if (b64) {
      setBusy(true);
      await play(b64);
      setBusy(false);
    }
  }, [hostAudio, play]);

  const currentStep = STEPS[stepIdx];

  useEffect(() => {
    if (stepIdx >= STEPS.length) {
      say('done').then(() => {
        const s = answers.subject;
        const subjectObj = s && s !== 'free'
          ? scenarios.find((x) => x.id === s) || null
          : null;
        onStart({
          langObj: { code: 'en', name: 'English', native_name: 'English', realtime: false },
          lvl: answers.depth || 'intermediate',
          scenarioObj: subjectObj,
          profile: { style: answers.style || 'encouraging', interests: [] },
        });
      });
      return;
    }
    // Only speak once the prefetched host audio for this step is ready —
    // the mount-time question must not be silent.
    if (hostAudio[currentStep]) {
      say(currentStep);
      setStatus('');
    }
  }, [stepIdx, hostAudio, currentStep]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleRecord = useCallback(async () => {
    if (recording) {
      // stop + parse
      setRecording(false);
      setBusy(true);
      setStatus('listening');
      try {
        recorderRef.current?.stop();
        const rec = recorderRef.current;
        const blob = rec ? rec._getBlob() : null;
        rec?._stream?.getTracks().forEach((tr) => tr.stop());
        if (!blob) throw new Error('no recording');
        const res = await setupVoiceParse(currentStep, blob);
        if (res.unclear) {
          if (retries < 2) {
            setRetries((r) => r + 1);
            setStatus('unclear');
            await say('retry');
            setStatus('');
          } else {
            // fall back to a sensible default rather than blocking
            const fallback = {
              subject: { choice: 'free', label: 'Free debate' },
              depth: { choice: 'intermediate', label: 'Balanced' },
              style: { choice: 'encouraging', label: 'Encouraging' },
            }[currentStep];
            setAnswers((a) => ({ ...a, [currentStep]: fallback.choice }));
            setRetries(0);
            setStepIdx((i) => i + 1);
          }
        } else {
          setAnswers((a) => ({ ...a, [currentStep]: res.choice }));
          setRetries(0);
          setStepIdx((i) => i + 1);
        }
      } catch (e) {
        console.error('voice setup failed:', e);
        setStatus('error');
      } finally {
        setBusy(false);
      }
      return;
    }
    // start recording (tap-to-record; the shared capture helper handles
    // mime picking incl. the iOS mp4 fallback)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickRecorderMime();
      let blobOut = null;
      const rec = startRecorder(stream, mime, {
        onBlob: (b) => { blobOut = b; },
        suppressSendRef: { current: false },
      });
      recorderRef.current = rec;
      recorderRef.current._stream = stream;
      recorderRef.current._getBlob = () => blobOut;
      setRecording(true);
      setStatus('');
    } catch {
      setStatus('mic_blocked');
    }
  }, [recording, currentStep, retries, say, scenarios, answers]);

  const stepLabel = {
    subject: '1 / 3 — Subject',
    depth: '2 / 3 — Depth',
    style: '3 / 3 — Style',
  }[currentStep] || '';

  const statusText = {
    listening: 'Listening to your answer…',
    unclear: 'Not quite — try again.',
    mic_blocked: 'Microphone blocked — allow it in the address bar.',
    error: 'Something went wrong — tap the mic to retry.',
  }[status] || '';

  return (
    <div className="screen setup-screen">
      <nav className="welcome-nav">
        <span className="topbar-spacer" />
        <button className="btn btn-ghost btn-sm" onClick={onBack}>{t('common.back')}</button>
      </nav>
      <div className="setup-body" style={{ alignItems: 'center', textAlign: 'center' }}>
        <h2 className="setup-title">🎙️ {t('voice_setup.title')}</h2>
        <p className="setup-hint">{stepLabel}</p>

        <button
          className="btn btn-primary setup-cta"
          style={{ minWidth: 220, marginTop: 18 }}
          disabled={busy}
          onClick={toggleRecord}
        >
          {recording ? '⏹ Stop and send' : '🎤 Speak your answer'}
        </button>

        {statusText && <p className="setup-hint" style={{ marginTop: 14 }}>{statusText}</p>}
        {busy && !recording && <p className="setup-hint" style={{ marginTop: 14 }}>…</p>}
      </div>
    </div>
  );
}
