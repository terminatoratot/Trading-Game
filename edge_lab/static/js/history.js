// Everything saved in this browser, and the dashboard built from it.
//
// Two stores: short session summaries (for the P&L chart and the recent list) and a per-question
// answer log (for pattern analysis). Answers from a session are only written once the session
// completes, so sessions ended early never count.

import { app } from './state.js';
import { attachTooltips, calibrationChart, calibrationTable, pnlChart } from './charts.js';
import { $, api, esc, num, plural, signed, store, toast } from './util.js';

const SUMMARIES = 'edge-lab-history';
const LOG = 'edge-lab-log';
const MAX_SUMMARIES = 30;
const MAX_LOG = 3000;

let latestProfile = null; // the last analysis from the server, used by the setup screen

export const summaries = () => store.get(SUMMARIES, []);
export const answerLog = () => store.get(LOG, []);
export const profile = () => latestProfile;

export function saveSummary(s) {
  const list = summaries();
  list.unshift({
    date: new Date().toISOString(),
    mode: s.mode,
    difficulty: s.difficulty,
    rounds: s.rounds,
    profit: s.profit,
    ev: s.expected_profit,
    error: s.mean_error_pp,
    seed: s.seed,
    rp: s.history.map(r => r.profit),
    re: s.history.map(r => r.expected_profit),
  });
  if (!store.set(SUMMARIES, list.slice(0, MAX_SUMMARIES))) {
    toast('Browser storage is unavailable. Export CSV to keep this session.');
  }
}

/** Log entries for one settled betting round (see insights.clean_log for the fields). */
export function entriesFromRound(result, session, hints = {}) {
  const bank = result.bank_before || 1;
  return result.events.map(x => ({
    t: Date.now(),
    mode: session.mode,
    diff: session.difficulty,
    fam: result.family,
    m: x.metric,
    q: x.label,
    p: x.p,
    e: x.estimate,
    h: hints[x.id] || 0,
    be: x.breakeven,
    ev: x.ev,
    k: x.coach.kind,
    s: x.stake / bank,
    sug: x.coach.suggested_stake / bank,
  }));
}

/** Log entries for the answers of a finished pricing drill. */
export function entriesFromDrill(summary) {
  return summary.answers.map(a => ({
    t: Date.now(),
    mode: 'drill',
    diff: summary.difficulty,
    fam: a.family,
    m: a.metric,
    q: a.label,
    p: a.p,
    e: a.estimate,
    h: 0,
  }));
}

/** Keep answers from the session in progress until we know it was completed. */
export function holdAnswers(entries) {
  app.pending.push(...entries);
}

export function commitAnswers() {
  if (!app.pending.length) return;
  store.set(LOG, answerLog().concat(app.pending).slice(-MAX_LOG));
  app.pending = [];
}

export function discardAnswers() {
  app.pending = [];
}

// ---- dashboard

function tendenciesPanel(pr) {
  if (!pr || !pr.estimates) return '';
  const issues = pr.issues.slice(0, 4);
  const intro = pr.ready
    ? issues.length
      ? 'Patterns found in your answers, worst first. Targeted practice deals boards that test exactly these.'
      : 'No clear weaknesses yet. Raise the difficulty, or keep playing to sharpen the picture.'
    : `Answer ${plural(pr.need - pr.estimates, 'more question')} to unlock pattern analysis. Your calibration so far is on the right.`;
  const cards = issues
    .map(
      i => `<div class="lesson ${esc(i.tone)}"><div class="eyebrow">${i.tone === 'bad' ? 'Fix this' : 'Worth a look'}</div>
      <h3>${esc(i.title)}</h3><p>${esc(i.body)}</p></div>`,
    )
    .join('');
  const bias = pr.mean_error;
  return `<div class="summary-panel">
    <div class="row spread"><h3>Your tendencies</h3><span class="tiny muted">Based on ${plural(pr.estimates, 'answer')}</span></div>
    <p class="tiny muted">${intro}</p>
    <div class="insights-grid">
      <div>
        ${cards}
        <div class="insights-actions">
          <button class="primary" id="practiceNow">Start targeted practice ↗</button>
          <button id="drillNow">Targeted pricing drill ↗</button>
        </div>
      </div>
      <div>
        ${calibrationChart(pr)}
        <div class="stat-row">
          <span>Average miss <strong>${num(pr.mean_abs_error, 1)} pts</strong></span>
          <span>Bias <strong>${signed(Number(bias.toFixed(1)))} pts</strong> (${bias > 0 ? 'too high' : 'too low'})</span>
          ${pr.slope === null ? '' : `<span>Slope <strong>${num(pr.slope, 2)}</strong> (perfect 1.00)</span>`}
        </div>
        <details><summary>Show as a table</summary>${calibrationTable(pr)}</details>
      </div>
    </div>
  </div>`;
}

function pnlPanel(list) {
  const rounds = [];
  [...list].reverse().forEach(s => {
    (s.rp || []).forEach((p, i) =>
      rounds.push({
        pnl: p,
        ev: (s.re || [])[i] || 0,
        start: i === 0,
        label: new Date(s.date).toLocaleDateString() + ' · ' + s.mode + ' · round ' + (i + 1),
      }),
    );
  });
  const shown = rounds.slice(-120);
  if (!shown.length) return '';
  const pnl = shown.reduce((t, x) => t + x.pnl, 0);
  const ev = shown.reduce((t, x) => t + x.ev, 0);
  const up = shown.filter(x => x.pnl > 0).length;
  return `<div class="summary-panel">
    <div class="row spread"><h3>P&amp;L across completed sessions</h3>
      <span class="tiny muted">${plural(shown.length, 'most recent round')}</span></div>
    <div class="metrics-mini">
      <div><span>Realised P&amp;L</span><strong class="${pnl < 0 ? 'negative' : 'positive'}">${signed(pnl)}</strong></div>
      <div><span>Expected profit</span><strong class="${ev < 0 ? 'negative' : 'positive'}">${signed(ev)}</strong></div>
      <div><span>Profitable rounds</span><strong>${up} / ${shown.length}</strong></div>
    </div>
    ${pnlChart(shown)}
    <p class="tiny muted">Vertical lines mark where a new session starts. Realised P&amp;L includes luck; the expected line shows what your
      chosen stakes were worth on average, so a gap between them is variance, not skill.</p>
  </div>`;
}

function recentList(list) {
  if (!list.length) return '';
  const rows = list
    .slice(0, 6)
    .map(s => {
      const result =
        s.mode === 'drill'
          ? `${s.correct} / ${s.answered} correct · best streak ${s.best}`
          : `EV <strong class="${s.ev < 0 ? 'negative' : 'positive'}">${signed(s.ev)}</strong> · P&amp;L ${signed(s.profit)}`;
      return `<div class="history-row"><span>${esc(new Date(s.date).toLocaleDateString())} · ${esc(s.mode)}</span>
        <span>${s.mode === 'drill' ? 'pricing drill' : plural(s.rounds, 'round')} · ${esc(s.difficulty)}</span>
        <span>${result}</span><span class="mono muted">${esc(s.seed || '')}</span></div>`;
    })
    .join('');
  return `<div class="row spread"><p class="section-label">Recent sessions on this browser</p>
    <button id="clearHistory" class="small ghost">Clear history</button></div>${rows}`;
}

/** Redraw the dashboard. Pattern analysis runs on the server, from the log kept here. */
export async function renderDashboard(onPractice, onDrill) {
  const list = summaries();
  const log = answerLog();
  $('savedHistory').innerHTML = recentList(list);
  latestProfile = null;
  if (log.length) {
    try {
      latestProfile = await api('/api/insights', { log });
    } catch (err) {
      toast('Could not analyse your history: ' + err.message);
    }
  }
  $('dashboard').innerHTML = tendenciesPanel(latestProfile) + pnlPanel(list);
  attachTooltips($('dashboard'));
  if ($('practiceNow')) $('practiceNow').onclick = onPractice;
  if ($('drillNow')) $('drillNow').onclick = onDrill;
  if ($('clearHistory')) {
    $('clearHistory').onclick = () => {
      if (!confirm('Clear saved sessions and your answer history from this browser?')) return;
      store.remove(SUMMARIES);
      store.remove(LOG);
      renderDashboard(onPractice, onDrill);
    };
  }
  document.dispatchEvent(new CustomEvent('profile-updated'));
}

/** Saved results for a finished drill, shown in the recent list alongside sessions. */
export function saveDrillSummary(s) {
  const list = summaries();
  list.unshift({
    date: new Date().toISOString(),
    mode: 'drill',
    difficulty: s.difficulty,
    answered: s.answered,
    correct: s.correct,
    best: s.best,
  });
  store.set(SUMMARIES, list.slice(0, MAX_SUMMARIES));
}
