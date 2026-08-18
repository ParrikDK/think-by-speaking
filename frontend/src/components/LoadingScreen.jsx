import { useState } from 'react';
import Waveform from './Waveform';
import { useT } from '../i18n/useI18n';

const MSG_COUNT = 7;
const TIP_COUNT = 7;

const MISSION_QUOTES = [
  { text: '"Everyone\'s a nutrition expert on the internet. I\'d rather debate one that has to answer back."', name: 'P' },
  { text: '"My cousin swears by keto, the gym bro is all about protein timing, my mom says dairy rots bones… I just want what\'s actually true."', name: 'P' },
  { text: '"I don\'t want a lecture. I want to argue and find out I\'m wrong on my own terms."', name: 'PD' },
  { text: '"Generic advice is useless. My life is not a statistics page."', name: 'PDK' },
  { text: '"Nobody argues back on social media. They just block you."', name: 'P' },
  { text: '"Debating out loud is how I actually find out what I think."', name: 'Parrik' },
  { text: '"One coach that knows my interests and always answers back? That\'s worth building."', name: 'PDK' },
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
