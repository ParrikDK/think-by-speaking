import Waveform from './Waveform';
import { useT } from '../i18n/useI18n';

export default function MicButton({
  recording = false,
  onToggle,
  disabled = false,
  connecting = false,
  handsFree = false,
  isSpeaking = false,
  small = false,
  lang = 'en',
}) {
  const t = useT(lang);

  const isActive = handsFree ? isSpeaking : recording;
  const isHardDisabled = disabled || connecting;

  const getLabel = () => {
    if (connecting) return t('mic.connecting');
    if (disabled) return t('mic.processing');
    if (handsFree) return isSpeaking ? t('chat.listening') : t('mic.hands_free');
    return recording ? t('mic.listening') : t('mic.tap');
  };

  let cls = small ? 'mic-btn mic-btn-sm' : 'mic-btn';
  if (isActive) cls += ' mic-btn-recording';
  if (isHardDisabled) cls += ' mic-btn-disabled';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
      <button
        className={cls}
        onClick={onToggle}
        disabled={isHardDisabled}
        aria-pressed={isActive}
        aria-label={getLabel()}
      >
        <Waveform active={isActive} color="var(--color-paper)" height={small ? 16 : 20} barWidth={2.5} gap={3} />
      </button>
      {!small && (
        <span className={isActive ? 'mic-caption mic-caption-active' : 'mic-caption'}>{getLabel()}</span>
      )}
    </div>
  );
}
