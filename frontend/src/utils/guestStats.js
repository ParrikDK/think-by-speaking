// Guest device memory (v13.1) — the personalization moat without an
// account: per-device debate analytics stored in localStorage, aggregated
// client-side with the same shape the server returns for logged-in users
// (stats_store.debate_trends). Bounded to the latest 200 turns.

const KEY = 'lf_guest_stats';
const MAX_TURNS = 200;

export function loadGuestTurns() {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function recordGuestCard(feedback, langCode) {
  if (!feedback || typeof feedback !== 'object') return;
  const turns = loadGuestTurns();
  turns.push({
    score: Number(feedback.score) || 50,
    fallacies: (Array.isArray(feedback.fallacies) ? feedback.fallacies : [])
      .map((f) => (f && f.type) || 'other'),
    fillers: Number(feedback.filler_count) || 0,
    lang: langCode || 'en',
    ts: Date.now(),
  });
  if (turns.length > MAX_TURNS) turns.splice(0, turns.length - MAX_TURNS);
  try {
    localStorage.setItem(KEY, JSON.stringify(turns));
  } catch {
    /* storage full/blocked — memory is best-effort */
  }
}

// Server-shaped aggregate (matches stats_store.debate_trends).
export function aggregateGuestTurns() {
  const turns = loadGuestTurns();
  if (!turns.length) return null;
  const byDay = {};
  const totals = { turns: 0, score_sum: 0, best: 0, fallacies: {}, fillers: 0 };
  for (const t of turns) {
    totals.turns += 1;
    totals.score_sum += t.score;
    totals.best = Math.max(totals.best, t.score);
    totals.fillers += t.fillers;
    for (const type of t.fallacies) {
      totals.fallacies[type] = (totals.fallacies[type] || 0) + 1;
    }
    const day = new Date(t.ts).toISOString().slice(0, 10);
    byDay[day] = byDay[day] || { score_sum: 0, turns: 0 };
    byDay[day].score_sum += t.score;
    byDay[day].turns += 1;
  }
  const history = Object.entries(byDay)
    .map(([day, seg]) => ({
      session_id: `device-${day}`,
      started_at: `${day}T00:00:00`,
      turns: seg.turns,
      avg_score: Math.round(seg.score_sum / seg.turns),
      best: 0,
    }))
    .sort((a, b) => (a.started_at < b.started_at ? 1 : -1));
  return {
    sessions: history.length,
    turns: totals.turns,
    avg_score: Math.round(totals.score_sum / totals.turns),
    best_score: totals.best,
    fallacy_totals: totals.fallacies,
    filler_total: totals.fillers,
    score_history: history.slice(0, 10),
    device: true,
  };
}
