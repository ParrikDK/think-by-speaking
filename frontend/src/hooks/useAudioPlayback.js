import { useState, useRef, useCallback, useEffect } from 'react';

export default function useAudioPlayback({ audioContext, onBargeIn, onEnded } = {}) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isBuffering, setIsBuffering] = useState(false);
  const audioRef = useRef(null);
  const genRef = useRef(0);

  const stop = useCallback(() => {
    genRef.current++; // invalidate any in-flight playback
    if (audioRef.current) {
      try {
        audioRef.current.pause();
        audioRef.current.src = '';
      } catch { /* already stopped */ }
      audioRef.current = null;
    }
    setIsPlaying(false);
  }, []);

  const play = useCallback(async (base64Audio, rate = 1) => {
    if (!base64Audio) return;
    stop();
    setIsBuffering(true);
    const gen = ++genRef.current; // capture generation AFTER stop

    try {
      const audio = new Audio(`data:audio/mpeg;base64,${base64Audio}`);
      audioRef.current = audio;

      audio.onended = () => {
        if (gen !== genRef.current) return; // superseded/stopped already
        setIsPlaying(false);
        audioRef.current = null;
        onEnded?.current?.();
      };

      audio.onerror = () => {
        if (gen !== genRef.current) return;
        console.error('Audio playback failed');
        setIsPlaying(false);
        audioRef.current = null;
        onEnded?.current?.();
      };

      await audio.play();
      if (gen !== genRef.current) return; // superseded while starting
      setIsBuffering(false);
      // Set playback rate AFTER play starts — HTMLAudioElement.playbackRate
      // is only reliable when applied after playback has begun.
      audio.playbackRate = rate;
      setIsPlaying(true);
    } catch (err) {
      if (gen !== genRef.current) return; // a superseded play's rejection
      setIsBuffering(false);
      console.error('Audio playback failed:', err);
      setIsPlaying(false);
      onEnded?.current?.(); // Notify ChatScreen so playingId resets even on failure
    }
  }, [stop, onEnded]);

  // Expose stop() to the VAD for barge-in
  useEffect(() => {
    if (onBargeIn) onBargeIn.current = stop;
  }, [onBargeIn, stop]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return { play, stop, isPlaying, isBuffering };
}
