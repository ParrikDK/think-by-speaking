/**
 * MediaRecorder helpers shared by the tap-to-speak and VAD recorders.
 * iOS Safari can't record webm — fall back to mp4 (Scribe accepts it).
 */

/** Best supported recorder mime for this browser ('' = browser default). */
export function pickRecorderMime() {
  if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) return 'audio/webm;codecs=opus';
  if (MediaRecorder.isTypeSupported('audio/mp4')) return 'audio/mp4';
  return '';
}

/** Blob type matching a recorder's actual mime (webm default). */
export function recorderBlobType(recorder) {
  return (recorder.mimeType || '').startsWith('audio/mp4') ? 'audio/mp4' : 'audio/webm';
}
