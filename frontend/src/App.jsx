import { useState, useCallback, useEffect, useRef, startTransition } from 'react';
import SetupScreen from './components/SetupScreen';
import VoiceSetupScreen from './components/VoiceSetupScreen';
import AuthModal from './components/AuthModal';
import LoadingScreen from './components/LoadingScreen';
import ChatScreen from './components/ChatScreen';
import RealtimeChatScreen from './components/RealtimeChatScreen';
import HistoryScreen from './components/HistoryScreen';
import ProgressScreen from './components/ProgressScreen';
import ToastStack from './components/ToastStack';
import {
  initChat, streamChat, summaryChat, regenerateTTS, getLanguages, getScenarios, getVoices, getMe, logout as apiLogout,
} from './api';
import STATIC_LANGUAGES from './i18n/languages';
import { analyzeAudio } from './utils/audioMetrics';
import { recordGuestCard } from './utils/guestStats';
import { useT } from './i18n/useI18n';

const STATIC_TARGET_LANGUAGES = STATIC_LANGUAGES.map((l) => ({
  code: l.code,
  name: l.english,
  native_name: l.native,
}));

// v13: learner profile (interests + debate style) persisted on-device and
// sent with every session — the personalization moat.
function loadProfile() {
  try {
    const raw = localStorage.getItem('lf_profile');
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function normalizeLanguage(l) {
  return {
    code: l.code,
    name: l.name || l.english || l.code,
    native_name: l.native_name || l.native || l.name || l.code,
    // v11 M2: routes setup to RealtimeChatScreen instead of the cascade.
    realtime: !!l.realtime,
  };
}

function detectUiLang() {
  const stored = localStorage.getItem('lf_ui_lang');
  if (stored) return stored;
  const nav = (navigator.language || 'en').toLowerCase();
  const exact = STATIC_LANGUAGES.find((l) => nav === l.code);
  if (exact) return exact.code;
  const prefix = STATIC_LANGUAGES.find((l) => nav.startsWith(l.code));
  return prefix ? prefix.code : 'en';
}

export default function App() {
  const [screen, setScreen] = useState('setup');
  const [uiLang, setUiLang] = useState(detectUiLang);
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState(null); // null | 'login' | 'register'
  const [toasts, setToasts] = useState([]);

  // Onboarding selections
  // The native language IS the interaction language: nativeLang tracks
  // uiLang below (v12.1 design; the setup-screen dropdown was removed
  // 2026-08-17 — no manual override path remains).
  const [nativeLang, setNativeLang] = useState(null);
  const [targetLang, setTargetLang] = useState(null);
  // v12.1: default level so "Start learning" is enabled right after
  // choosing a language (the greyed-out CTA was a dead end).
  const [level, setLevel] = useState('beginner');
  const [scenario, setScenario] = useState(null); // null = free talk
  const [profile, setProfile] = useState(loadProfile); // v13: interests + style
  const [voices, setVoices] = useState([]);
  // v13 voice picker: British male default (user-directed 2026-08-18)
  const [voiceId, setVoiceId] = useState('en-GB-RyanNeural');

  // Data
  const [languages, setLanguages] = useState(STATIC_TARGET_LANGUAGES);
  const [scenarios, setScenarios] = useState([]);

  // Chat session
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const recapShownRef = useRef(false); // spoken recap fires once per session
  const msgIdRef = useRef(1);
  const sendingRef = useRef(false);
  const toastSeqRef = useRef(1);
  const toastTimeoutRef = useRef([]);

  const nextMsgId = () => msgIdRef.current++;

  // ── Toasts ──
  const notify = useCallback((message, type = 'error') => {
    const id = toastSeqRef.current++;
    setToasts((prev) => [...prev, { id, message, type }]);
    const tid = setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4200);
    toastTimeoutRef.current.push(tid);
  }, []);

  // ── Boot: restore session, fetch languages + scenarios ──
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((data) => { if (!cancelled && data?.user) setUser(data.user); })
      .catch((e) => { console.error('getMe failed:', e); if (!cancelled) notify('boot.error_get_me'); });
    getLanguages()
      .then((list) => { if (!cancelled && Array.isArray(list) && list.length) setLanguages(list.map(normalizeLanguage)); })
      .catch((e) => { console.error('getLanguages failed:', e); if (!cancelled) notify('boot.error_get_languages'); });
    getScenarios()
      .then((list) => { if (!cancelled && Array.isArray(list)) setScenarios(list); })
      .catch((e) => { console.error('getScenarios failed:', e); if (!cancelled) notify('boot.error_get_scenarios'); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    document.documentElement.lang = uiLang;
    localStorage.setItem('lf_ui_lang', uiLang);
    // Native language = interaction language (no longer overridable).
    const l = STATIC_LANGUAGES.find((x) => x.code === uiLang);
    if (l) setNativeLang({ code: l.code, name: l.english, native_name: l.native });
  }, [uiLang]);

  // Persist the learner profile across sessions
  useEffect(() => {
    localStorage.setItem('lf_profile', JSON.stringify(profile));
  }, [profile]);

  // ── Voices (v13): fetch per debate language; default = first option of
  // the provider the session kind uses (edge for cascade, realtime for WS).
  useEffect(() => {
    if (!targetLang) return;
    let cancelled = false;
    getVoices(targetLang.code)
      .then((list) => {
        if (cancelled || !Array.isArray(list)) return;
        setVoices(list);
        const usable = list.filter((v) =>
          targetLang.realtime ? v.provider === 'realtime' : v.provider !== 'realtime'
        );
        if (usable.length && !usable.some((v) => v.voice_id === voiceId)) {
          setVoiceId(usable[0].voice_id);
        }
      })
      .catch((e) => console.error('getVoices failed:', e));
    return () => { cancelled = true; };
  }, [targetLang?.code]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Toast timeout cleanup ──
  useEffect(() => {
    return () => {
      toastTimeoutRef.current.forEach(clearTimeout);
      toastTimeoutRef.current = [];
    };
  }, []);

  // ── Chat lifecycle ──
  const startChat = useCallback(async ({ langObj, lvl, scenarioObj, profile: p }) => {
    const prof = p && Object.keys(p).length ? p : profile;
    startTransition(() => {
      setTargetLang(langObj);
      setLevel(lvl);
      setScenario(scenarioObj || null);
      if (prof && Object.keys(prof).length) setProfile(prof);
      // Realtime-capable languages (v11 M2) go straight to the WS voice
      // screen — no initChat; the session starts on the first mic tap or
      // typed line. Everything else stays on the cascade engine below.
      setScreen(langObj.realtime ? 'realtime' : 'loading');
    });
    if (langObj.realtime) return;
    try {
      const res = await initChat({
        language: langObj.code,
        nativeLanguage: nativeLang?.code || 'en',
        level: lvl,
        scenarioId: scenarioObj?.id || '',
        profile: prof,
        voiceId,
      });
      setSessionId(res.session_id);
      const g = res.greeting || {};
      msgIdRef.current = 1;
      setMessages([{
        id: nextMsgId(),
        role: 'tutor',
        text: g.text || '',
        translation: g.translation || null,
        feedback: null,
        audio: g.audio_base64 || null,
        streaming: false,
      }]);
      setScreen('chat');
    } catch (e) {
      console.error('initChat failed:', e);
      notify('chat.error_init');
      setScreen('setup');
    }
  }, [profile, nativeLang, voiceId, notify]);

  const sendChat = useCallback(async ({ blob, text }) => {
    if (!sessionId || !targetLang || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);

    const userId = nextMsgId();
    const tutorId = nextMsgId();
    const isTyped = typeof text === 'string';

    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', text: isTyped ? text : '', pending: !isTyped, feedback: null },
      { id: tutorId, role: 'tutor', text: '', streaming: true },
    ]);

    let streamed = '';
    // v13.1 delivery pillar: measure the recording (duration + pitch
    // variance) so the card can show pace and monotone detection.
    const metrics = blob && !isTyped ? await analyzeAudio(blob) : { audioSecs: 0, pitchVar: 0 };
    try {
      const res = await streamChat({
        sessionId,
        language: targetLang.code,
        audioBlob: blob,
        text: isTyped ? text : undefined,
        audioSecs: metrics.audioSecs || undefined,
        pitchVar: metrics.pitchVar || undefined,
        onToken: (tok) => {
          streamed += tok;
          const snapshot = streamed;
          setMessages((prev) => prev.map((m) => (m.id === tutorId ? { ...m, text: snapshot } : m)));
        },
        onAudio: (audioBase64) => {
          // Audio arrives on a separate SSE event after "complete" — attach it
          // to the tutor message; ChatScreen auto-plays when it lands.
          if (!audioBase64) return;
          setMessages((prev) => prev.map((m) => (m.id === tutorId ? { ...m, audio: audioBase64 } : m)));
        },
      });

      const reply = res.reply || {};
      const userText = res.user_text ?? (isTyped ? text : '');
      const errorType = res.error_type || null;

      // v13.1 guest memory: device-local analytics for logged-out users
      if (!user && reply.feedback) {
        recordGuestCard(reply.feedback, targetLang?.code);
      }

      setMessages((prev) => prev.map((m) => {
        if (m.id === userId) {
          return {
            ...m,
            text: userText,
            pending: false,
            noSpeech: !isTyped && userText === '',
            feedback: userText ? (reply.feedback || null) : null,
            error_type: errorType,
          };
        }
        if (m.id === tutorId) {
          return {
            id: tutorId,
            role: 'tutor',
            text: reply.text || streamed,
            translation: reply.translation || null,
            feedback: null,
            // "complete" never carries audio (skip_audio) — preserve whatever
            // the onAudio event attached earlier.
            audio: reply.audio_base64 || m.audio || null,
            streaming: false,
            error_type: errorType,
          };
        }
        return m;
      }));
    } catch (e) {
      console.error('sendChat failed:', e);
      // Keep any accumulated streamed text — don't nuke the tutor message.
      // Mark it as interrupted so the user sees what was received and can retry.
      setMessages((prev) => prev.map((m) => {
        if (m.id === tutorId && streamed) {
          return { ...m, text: streamed, streaming: false, interrupted: true };
        }
        // In voice mode, remove the pending user bubble (it was never sent).
        // In text mode, the user's own typed message stays visible.
        if (m.id === userId && !isTyped) return null;
        return m;
      }).filter(Boolean));
      notify('chat.error_send');
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [sessionId, targetLang, notify]);

  const handleSendAudio = useCallback((blob) => sendChat({ blob }), [sendChat]);
  const handleSendText = useCallback((text) => sendChat({ text }), [sendChat]);

  // ── Regenerate audio for a TTS-failed message ──
  const handleRegenerateAudio = useCallback(async (msgId, text) => {
    if (!sessionId || !targetLang) return;
    try {
      const data = await regenerateTTS({ sessionId, text, language: targetLang.code });
      setMessages((prev) => prev.map((m) =>
        m.id === msgId && data.audio_base64 ? { ...m, audio: data.audio_base64 } : m
      ));
    } catch (e) {
      console.error('TTS regen failed:', e);
      notify('chat.error_tts_regen', 'Audio generation failed');
    }
  }, [sessionId, targetLang, notify]);

  const endSession = useCallback(async () => {
    // v13.1 spoken recap: on the cascade chat screen, End first asks the
    // coach for a spoken session summary (once), then exits.
    if (screen === 'chat' && sessionId && !recapShownRef.current) {
      recapShownRef.current = true;
      try {
        const res = await summaryChat(sessionId, targetLang?.code || 'en');
        const r = res.reply || {};
        setMessages((prev) => [...prev, {
          id: nextMsgId(), role: 'tutor', text: r.text || '',
          translation: r.translation || null, feedback: null,
          audio: r.audio_base64 || null, streaming: false,
        }]);
        return; // the recap plays; 'new conversation' exits
      } catch (e) {
        console.error('summary failed:', e);
      }
    }
    setMessages([]);
    setSessionId(null);
    setScreen('setup');
  }, [screen, sessionId, targetLang]);

  const newConversation = useCallback(() => {
    if (!targetLang || !level) return;
    // Clear current session, reset message counter, start fresh
    setMessages([]);
    setSessionId(null);
    msgIdRef.current = 1;
    startChat({ langObj: targetLang, lvl: level, scenarioObj: scenario });
  }, [targetLang, level, scenario, startChat]);

  // ── "Practice again" from history/progress — starts a FRESH session with
  // the same language/level/scenario (real conversation resume is a v9 TODO;
  // relabelled 2026-08-03 review finding 12).
  const handleResume = useCallback((summary) => {
    const langObj = languages.find((l) => l.code === summary.language)
      || { code: summary.language, name: summary.language, native_name: summary.language };
    const scenarioObj = scenarios.find((s) => s.id === summary.scenario_id) || null;
    startChat({ langObj, lvl: summary.level || 'intermediate', scenarioObj });
  }, [languages, scenarios, startChat]);

  // ── Auth ──
  const handleAuthSuccess = useCallback((u) => {
    setUser(u);
    setAuthMode(null);
  }, []);

  const handleLogout = useCallback(async () => {
    await apiLogout().catch(() => {});
    setUser(null);
  }, []);

  // ── Toast messages are i18n keys; translate at render time ──
  const t = useT(uiLang);

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}>
      {screen === 'setup' && (
        <SetupScreen
          lang={uiLang}
          uiLang={uiLang}
          onUiLangChange={setUiLang}
          languages={languages}
          scenarios={scenarios}
          targetLang={targetLang}
          level={level}
          profile={profile}
          onProfileChange={setProfile}
          voices={voices}
          voiceId={voiceId}
          onVoiceSelect={setVoiceId}
          user={user}
          onLogin={() => setAuthMode('login')}
          onLogout={handleLogout}
          onProgress={() => setScreen('progress')}
          onTargetSelect={(l) => {
            // SetupScreen's dropdown uses the static list — re-attach the
            // API's realtime flag by code (v11 M2 routing).
            const fromApi = languages.find((x) => x.code === l.code);
            setTargetLang({ code: l.code, name: l.english, native_name: l.native, realtime: !!fromApi?.realtime });
          }}
          onLevelSelect={setLevel}
          onVoiceSetup={() => setScreen('voicesetup')}
          onStart={({ langObj, lvl, scenarioObj, profile: p }) =>
            startChat({ langObj, lvl, scenarioObj, profile: p })
          }
        />
      )}

      {screen === 'voicesetup' && (
        <VoiceSetupScreen
          scenarios={scenarios}
          onBack={() => setScreen('setup')}
          onStart={startChat}
        />
      )}

      {screen === 'loading' && <LoadingScreen lang={uiLang} />}

      {screen === 'realtime' && targetLang && (
        <RealtimeChatScreen
          lang={uiLang}
          targetLang={targetLang}
          level={level}
          scenario={scenario}
          nativeLang={nativeLang}
          profile={profile}
          voice={voiceId}
          onEndSession={endSession}
          onLoginRequest={() => setAuthMode('register')}
        />
      )}

      {screen === 'chat' && (
        <ChatScreen
          lang={uiLang}
          targetLang={targetLang}
          level={level}
          scenario={scenario}
          messages={messages}
          sending={sending}
          onSendAudio={handleSendAudio}
          onSendText={handleSendText}
          onRegenerateAudio={handleRegenerateAudio}
          onEndSession={endSession}
          onNewConversation={newConversation}
          onNavigate={(s) => setScreen(s)}
          user={user}
        />
      )}

      {screen === 'history' && (
        <HistoryScreen
          lang={uiLang}
          user={user}
          languages={languages}
          scenarios={scenarios}
          onResume={handleResume}
          onBack={() => setScreen(sessionId ? 'chat' : 'setup')}
          onLoginRequest={() => setAuthMode('login')}
          notify={notify}
        />
      )}

      {screen === 'progress' && (
        <ProgressScreen
          lang={uiLang}
          user={user}
          languages={languages}
          onResume={handleResume}
          onBack={() => setScreen(sessionId ? 'chat' : 'setup')}
          onLoginRequest={() => setAuthMode('login')}
        />
      )}

      {authMode && (
        <AuthModal
          mode={authMode}
          lang={uiLang}
          onSuccess={handleAuthSuccess}
          onClose={() => setAuthMode(null)}
        />
      )}

      <ToastStack toasts={toasts.map((toast) => ({ ...toast, message: t(toast.message, toast.message) }))} />
    </div>
  );
}
