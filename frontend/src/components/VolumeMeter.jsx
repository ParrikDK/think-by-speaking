import { useMemo } from 'react';
import './volume-meter.css';

const BAR_COUNT = 5;

export default function VolumeMeter({ volume = 0, barCount = BAR_COUNT, color = 'var(--color-voice)' }) {
  const bars = useMemo(() => {
    return Array.from({ length: barCount }, (_, i) => {
      // Each bar activates progressively as volume rises past its threshold
      const threshold = (i + 1) / barCount;
      const barVolume = Math.max(0, Math.min(1, (volume - i / barCount) * barCount));
      return {
        height: Math.max(3, barVolume * 14 + 3),
        opacity: Math.max(0.12, barVolume),
      };
    });
  }, [volume, barCount]);

  return (
    <span className="volume-meter" aria-hidden="true" style={{ '--meter-color': color }}>
      {bars.map((b, i) => (
        <span
          key={i}
          className="volume-meter-bar"
          style={{
            height: b.height,
            opacity: b.opacity,
          }}
        />
      ))}
    </span>
  );
}
