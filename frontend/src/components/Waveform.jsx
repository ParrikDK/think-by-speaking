import './waveform.css';

// Relative bar heights create the "breathing" ink-stroke shape.
// Kept as a module constant so every instance of the waveform reads as the same mark.
const BAR_HEIGHTS = [0.4, 0.7, 1, 0.6, 0.3];

export default function Waveform({
  active = false,
  color = 'var(--color-voice)',
  barWidth = 2,
  gap = 2,
  height = 16,
}) {
  return (
    <span className="waveform" style={{ height, gap }} aria-hidden="true">
      {BAR_HEIGHTS.map((h, i) => (
        <span
          key={i}
          className={active ? 'waveform-bar waveform-bar-active' : 'waveform-bar'}
          style={{
            width: barWidth,
            height: `${h * 100}%`,
            background: color,
            animationDelay: `${i * 0.12}s`,
          }}
        />
      ))}
    </span>
  );
}
