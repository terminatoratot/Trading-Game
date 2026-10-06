// Pricing drill: one question at a time against a single clock. No odds, no stakes, just streaks.

import { app } from './state.js';
import {
  answerLog,
  commitAnswers,
  discardAnswers,
  entriesFromDrill,
  holdAnswers,
  saveDrillSummary,
} from './history.js';
import { backToSetup } from './play.js';
import {
  $,
  api,
  boardGraphic,
  clock,
  describeTyped,
  esc,
  num,
  parseProb,
  pct,
  plural,
  screen,
  signed,
  toast,
} from './util.js';

let clockHandle = null;
let lastConfig = null; // for "Drill again"

export async function startDrill(cfg) {
  if (app.busy) return;
  app.busy = true;
  lastConfig = cfg;
  try {
    const drill = await api('/api/drill/start', { ...cfg, log: cfg.targeted ? answerLog() : undefined });
    app.drill = { ...drill, endsAt: Date.now() + drill.remaining * 1000, pending: false };
    discardAnswers();
    $('drillFeedback').innerHTML =
      '<p class="muted">Type a percentage or a fraction and press Enter. Feedback on each answer appears here while the next question is already waiting.</p>';
    $('drillLast').textContent = '–';
    screen('drill');
    renderQuestion();
    clearInterval(clockHandle);
    clockHandle = setInterval(tickClock, 200);
    tickClock();
  } catch (err) {
    toast(err.message);
  } finally {
    app.busy = false;
  }
}

function renderScore() {
  const d = app.drill;
  $('drillLabel').textContent = 'PRICING DRILL / ' + d.difficulty.toUpperCase();
  $('drillTolerance').textContent = `Within ±${d.tolerance} points counts`;
  $('drillScore').textContent = `${d.correct} / ${d.answered}`;
  $('drillStreak').textContent = d.streak;
  $('drillBest').textContent = 'Best ' + d.best;
}

function renderQuestion() {
  const q = app.drill.question;
  renderScore();
  if (!q) return;
  $('drillFamily').textContent = `QUESTION ${q.number} / ${q.topic.toUpperCase()}`;
  $('drillTitle').textContent = q.title;
  $('drillRules').textContent = q.rules;
  $('drillGraphic').innerHTML = boardGraphic(q.kind, q.slots);
  $('drillQuestion').textContent = q.label + '?';
  $('drillFocus').textContent = q.focus_note || '';
  $('drillFocus').classList.toggle('hidden', !q.focus_note);
  $('drillInput').value = '';
  $('drillParsed').textContent = '';
  $('drillInput').focus({ preventScroll: true });
}

function renderFeedback(f) {
  const verdict = f.within ? '✓ In range' : '✗ Missed';
  const card = $('drillFeedback');
  card.innerHTML = `<div class="eyebrow muted">LAST ANSWER · ${esc(f.title)}</div>
    <h4>${esc(f.label)}</h4>
    <div class="drill-verdict ${f.within ? 'good' : 'bad'}">${verdict}</div>
    <p>You said <strong>${num(f.estimate, 2)}%</strong>, the truth is <strong>${pct(f.p)}</strong>
      (${signed(Number(f.error.toFixed(2)))} points) · ${num(f.seconds, 1)} s</p>
    <p><strong>${esc(f.counting)}</strong></p>
    <p>${esc(f.tip)}</p>`;
  card.classList.remove('flash-good', 'flash-bad');
  void card.offsetWidth; // restart the flash animation
  card.classList.add(f.within ? 'flash-good' : 'flash-bad');
  $('drillLast').textContent = f.within ? '✓' : num(Math.abs(f.error), 1);
}

export async function answerDrill(event) {
  event.preventDefault();
  const d = app.drill;
  if (!d || d.pending || d.finished) return;
  const value = parseProb($('drillInput').value);
  if (value === null) {
    toast('Enter a probability: 0 to 100, or a fraction like 5/12.');
    return;
  }
  d.pending = true;
  try {
    const { feedback, drill } = await api('/api/drill/answer', {
      id: d.id,
      number: d.question.number,
      estimate: value,
    });
    Object.assign(d, drill, { question: drill.question || null });
    if (feedback) renderFeedback(feedback);
    if (drill.finished) finishDrill(true);
    else renderQuestion();
  } catch (err) {
    toast(err.message);
  } finally {
    d.pending = false;
  }
}

export function showTyped() {
  const hint = describeTyped($('drillInput').value);
  $('drillParsed').textContent = hint.text;
  $('drillParsed').className = 'parsed tiny ' + (hint.bad ? 'negative' : 'muted');
}

function tickClock() {
  const d = app.drill;
  if (!d) return;
  const left = (d.endsAt - Date.now()) / 1000;
  $('drillClock').textContent = clock(left);
  $('drillClock').classList.toggle('negative', left < 10);
  if (left <= 0 && !d.finished) finishDrill(true);
}

/** `completed` is false when the player ends early; those answers are then not kept. */
export async function finishDrill(completed) {
  const d = app.drill;
  if (!d || d.closing) return;
  d.closing = true;
  d.finished = true;
  clearInterval(clockHandle);
  try {
    const summary = await api('/api/drill/finish', { id: d.id });
    if (completed && summary.answered) {
      holdAnswers(entriesFromDrill(summary));
      commitAnswers();
      saveDrillSummary(summary);
    } else {
      discardAnswers();
    }
    renderDrillSummary(summary, completed);
    screen('summaryView');
  } catch (err) {
    toast(err.message);
    backToSetup();
  } finally {
    app.drill = null;
  }
}

function renderDrillSummary(s, completed) {
  const accuracy = s.answered ? Math.round((100 * s.correct) / s.answered) : 0;
  const misses = s.misses
    .map(
      m => `<div class="lesson bad"><div class="eyebrow">${esc(m.title)} · missed by ${num(Math.abs(m.error), 1)} points</div>
      <h3>${esc(m.label)}</h3>
      <p>You said ${num(m.estimate, 2)}%, the truth is ${pct(m.p)}. ${esc(m.counting)} ${esc(m.tip)}</p></div>`,
    )
    .join('');
  $('summaryView').innerHTML = `
    <div class="session-top">
      <div>
        <div class="eyebrow muted">${completed ? 'DRILL COMPLETE' : 'DRILL ENDED EARLY'} / ${esc(s.difficulty.toUpperCase())}</div>
        <h1 style="font-size:42px;margin-top:10px">${s.correct} in range.</h1>
        <p class="muted">${plural(s.answered, 'answer')} in ${clock(s.seconds)} · accepted within ±${s.tolerance} points</p>
      </div>
      <div class="row"><button id="drillAgain" class="primary">Drill again ↗</button><button id="drillBack" class="ghost">Dashboard</button></div>
    </div>
    ${completed ? '' : '<div class="warning">You ended this drill early, so it is not saved to your dashboard or answer history.</div>'}
    <div class="stats">
      <div class="stat"><span>Accuracy</span><strong>${accuracy}%</strong><small>${s.correct} of ${s.answered} in range</small></div>
      <div class="stat"><span>Best streak</span><strong>${s.best}</strong><small>In a row</small></div>
      <div class="stat"><span>Average miss</span><strong>${s.mean_abs_error === null ? '–' : num(s.mean_abs_error, 1)}</strong><small>Points from the truth</small></div>
      <div class="stat"><span>Pace</span><strong>${s.mean_seconds === null ? '–' : num(s.mean_seconds, 1) + 's'}</strong><small>Per answer</small></div>
    </div>
    <div class="summary-panel"><h3>${misses ? 'Your biggest misses' : 'No misses. Try a harder difficulty.'}</h3>${misses}</div>`;
  $('drillAgain').onclick = () => startDrill(lastConfig);
  $('drillBack').onclick = backToSetup;
}
