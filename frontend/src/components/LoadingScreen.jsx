import { useState } from 'react';
import Waveform from './Waveform';
import { useT } from '../i18n/useI18n';

const MSG_COUNT = 7;
const TIP_COUNT = 7;

const MISSION_QUOTES = [
  { text: '"I want to order food in Mandarin."', name: 'Parrik' },
  { text: '"Job market not easy I heard, knowing Mandarin Cantonese English is advantage like a degree itself."', name: 'P' },
  { text: '"Online tutors charge like how much? I\'d rather build one…"', name: 'PD' },
  { text: '"Websites and YouTube are great, but I want the reality of actually speaking practicing."', name: 'PDK' },
  { text: '"Want to be able practice freely, comfortably. Like late night or even while waiting or commuting."', name: 'P' },
  { text: '"Online tutors? Nah."', name: 'Parrik' },
  { text: '"I\'m going to build one!"', name: 'PDK' },
];

function pickRandom(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

export default function LoadingScreen({ lang }) {
  const t = useT(lang);
  // ONE random message/tip/quote per screen load — no rotation (user-directed
  // 2026-08-03, same as v8C). Indices are stable so t() re-evaluates if lang changes.
  const [quote] = useState(() => pickRandom(MISSION_QUOTES));
  const [msgIdx] = useState(() => Math.floor(Math.random() * MSG_COUNT) + 1);
  const [tipIdx] = useState(() => Math.floor(Math.random() * TIP_COUNT) + 1);

  const msg = t(`loading.msg_${msgIdx}`);
  const tip = t(`loading.tip_${tipIdx}`);

  return (
    <div className="screen">
      <div className="loading-wrap">
        <div style={{ marginBottom: 8 }}>
          <Waveform active={true} color="var(--color-voice)" height={32} barWidth={4} gap={5} />
        </div>

        <p className="loading-msg">{msg}</p>

        {/* Mission quote card */}
        <div className="loading-quote-card">
          <div className="loading-quote-text">{quote.text}</div>
          <div className="loading-quote-name">— {quote.name}</div>
        </div>

        {/* Tip card */}
        <p className="loading-tip">{t('loading.tip_label')} {tip}</p>
      </div>
    </div>
  );
}
