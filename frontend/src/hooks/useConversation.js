import { useCallback, useReducer, useRef } from 'react';
import { streamChat } from '../api';

/**
 * useConversation — the chat turn state machine (arch review candidate 3,
 * 2026-08-06). The SSE event protocol is now a PURE REDUCER over message
 * state; streamChat is driven here, and only side effects (audio playback,
 * aborting) touch refs. Before, this logic lived as imperative setMessages
 * closures interleaved with ref mirrors in App.sendChat — every frontend
 * audit bug (F4 audio_full never played, F5 retry duplication, F9 abort,
 * F10 queue ordering) was a merge/ordering bug in that closure.
 *
 * Actions: TURN_START / TOKEN / AUDIO / AUDIO_FULL / AUDIO_CLEAR /
 * COMPLETE / RETRY_RESET / ABORT / TURN_END / REPLACE
 */
const initialState = { messages: [], sending: false };

function withTutor(state, patch) {
  return { ...state, messages: state.messages.map((m) => (
    m.id === state._tutorId ? { ...m, ...patch } : m
  )) };
}

export function conversationReducer(state, action) {
  switch (action.type) {
    case 'TURN_START':
      return {
        ...state,
        sending: true,
        _userId: action.userId,
        _tutorId: action.tutorId,
        messages: [
          ...state.messages,
          { id: action.userId, role: 'user', text: action.isTyped ? action.text : '', pending: !action.isTyped, grammar: null },
          { id: action.tutorId, role: 'tutor', text: '', streaming: true },
        ],
      };
    case 'TOKEN':
      return withTutor(state, { text: action.text });
    case 'AUDIO':
      return withTutor(state, { audioChunks: [...(state.messages.find((m) => m.id === state._tutorId)?.audioChunks || []), action.b64] });
    case 'AUDIO_FULL':
      return withTutor(state, { audioChunks: [action.b64] });
    case 'AUDIO_CLEAR':
      return withTutor(state, { audioChunks: [] });
    case 'COMPLETE':
      return {
        ...state,
        messages: state.messages.map((m) => {
          if (m.id === state._userId) {
            return {
              ...m,
              text: action.userText ?? m.text,
              pending: false,
              noSpeech: !action.isTyped && action.userText === '',
              pronunciation: action.userPronunciation || null,
              grammar: action.userText ? (action.reply.grammar || null) : null,
              error_type: action.errorType,
            };
          }
          if (m.id === state._tutorId) {
            return {
              id: m.id,
              role: 'tutor',
              text: action.reply.text || m.text,
              translation: action.reply.translation || null,
              pronunciation: action.reply.pronunciation || null,
              grammar: null,
              audio: action.reply.audio_base64 || m.audio || null,
              audioChunks: m.audioChunks,
              streaming: false,
              error_type: action.errorType,
            };
          }
          return m;
        }),
      };
    case 'RETRY_RESET':
      return withTutor(state, { text: '', audioChunks: [] });
    case 'ABORT':
      // Swarm H1 (2026-08-06): a failed turn must NOT leave the tutor
      // bubble permanently streaming — that dead-ends the message.
      return withTutor(state, { interrupted: true, streaming: false });
    case 'REMOVE_PENDING_USER':
      return { ...state, messages: state.messages.filter((m) => m.id !== action.userId) };
    case 'UPDATE_AUDIO': // regenerate-TTS patch
      return { ...state, messages: state.messages.map((m) => (
        m.id === action.msgId ? { ...m, audio: action.audio } : m
      )) };
    case 'TURN_END':
      return { ...state, sending: false, _tutorId: null, _userId: null };
    case 'REPLACE': // init greeting / fresh session
      return { ...initialState, messages: action.message ? [action.message] : [] };
    default:
      return state;
  }
}

/**
 * @param {object} opts — { liveAudioRef } (playback controller; may be null
 *   before ChatScreen mounts — playback then just doesn't auto-voice).
 */
export default function useConversation({ liveAudioRef } = {}) {
  const [state, dispatch] = useReducer(conversationReducer, initialState);
  const abortRef = useRef(null);
  const nextIdRef = useRef(1);

  const nextMsgId = () => nextIdRef.current++;

  const sendTurn = useCallback(async ({ sessionId, language, blob, text }) => {
    if (state.sending) return;
    const isTyped = typeof text === 'string';
    const userId = nextMsgId();
    const tutorId = nextMsgId();
    dispatch({ type: 'TURN_START', userId, tutorId, isTyped, text: text ?? '' });

    const abort = new AbortController();
    abortRef.current = abort;
    let streamed = '';
    try {
      const res = await streamChat({
        sessionId,
        language,
        audioBlob: blob,
        text: isTyped ? text : undefined,
        signal: abort.signal,
        onToken: (tok) => {
          streamed += tok;
          dispatch({ type: 'TOKEN', text: streamed });
        },
        onRetry: () => {
          streamed = '';
          dispatch({ type: 'RETRY_RESET' });
          liveAudioRef?.current?.clear?.();
        },
        onAudio: (audioBase64, isFull) => {
          if (!audioBase64) return;
          liveAudioRef?.current?.enqueue?.(audioBase64, tutorId);
          dispatch({ type: isFull ? 'AUDIO_FULL' : 'AUDIO', b64: audioBase64 });
        },
        onAudioClear: () => {
          liveAudioRef?.current?.clear?.();
          dispatch({ type: 'AUDIO_CLEAR' });
        },
      });
      const reply = res.reply || {};
      const userText = res.user_text ?? (isTyped ? text : '');
      dispatch({
        type: 'COMPLETE',
        reply,
        userText,
        userPronunciation: res.user_pronunciation || '',
        isTyped,
        errorType: res.error_type || null,
      });
    } catch (e) {
      console.error('sendTurn failed:', e);
      // Keep any accumulated streamed text — don't nuke the tutor message.
      dispatch({ type: 'ABORT' });
      if (!isTyped) {
        // In voice mode, remove the pending user bubble (it was never sent).
        dispatch({ type: 'REMOVE_PENDING_USER', userId });
      }
      throw e;
    } finally {
      if (abortRef.current === abort) abortRef.current = null;
      dispatch({ type: 'TURN_END' });
    }
  }, [state.sending, liveAudioRef]);

  const replaceMessages = useCallback((message) => {
    nextIdRef.current = 1;
    dispatch({ type: 'REPLACE', clearAll: true, message });
  }, []);

  const clearMessages = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: 'REPLACE', message: null });
  }, []);

  const updateMessageAudio = useCallback((msgId, audio) => {
    dispatch({ type: 'UPDATE_AUDIO', msgId, audio });
  }, []);

  return {
    messages: state.messages,
    sending: state.sending,
    sendTurn,
    replaceMessages,
    clearMessages,
    updateMessageAudio,
  };
}
