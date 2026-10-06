// What the player sees after committing: coach hints, the reveal, the debrief and the session report.

import { app } from './state.js';
import { histogram, lineChart, pnlChart } from './charts.js';
import { $, KIND_LABEL, download, esc, num, pct, signed, toast } from './util.js';

// ---- Coach hint ladder: a nudge, then the method, then the full walkthrough

const HINT_BUTTONS = ['Hint 1 · Approach', 'Hint 2 · Method', 'Show full walkthrough'];

function walkthrough(e) {
  const a = e.answer;
  const good = a.ev > 1e-9;
  const gap = 100 * (a.p - a.breakeven);
  const clear = a.fair_odds * 1.1;
  const stake = app.session.bank * a.kelly * 0.5;
  const price = good
    ? `You are offered ${num(e.odds)} : 1, better than fair, so you are paid more than the risk deserves.` +
      (e.odds < clear
        ? ` The edge is thin: a small error in your own estimate could erase it. A clear buy would pay about ${num(clear, 2)} : 1.`
        : '')
    : `You are offered ${num(e.odds)} : 1, so you are underpaid. It would need ${num(a.fair_odds, 2)} : 1 to break even and about ${num(clear, 2)} : 1 to be a clear buy.`;
  const size = good
    ? `Kelly sizing stakes the fraction of your bankroll that maximises long-run growth for this bet on its own:
       [p(b+1) − 1] ÷ b = ${pct(a.kelly)}. Half of that is ${pct(a.kelly * 0.5)}, or <strong>${num(stake)} u</strong>.
       Halving costs little growth and cuts the swings a lot, which matters because this bet only wins about 1 time in ${num(1 / a.p, 1)}.`
    : 'Kelly sizing says to stake nothing on a bet with no edge, so the size is 0 u. Passing is a decision.';
  return `<div class="notes"><ol class="steps">
      <li><strong>1 · Probability: ${pct(a.p)}.</strong> ${esc(a.method)} ${esc(a.counting)}<br><em>Shortcut:</em> ${esc(a.tip)}</li>
      <li><strong>2 · Break-even: ${pct(a.breakeven)}.</strong> At ${num(e.odds)} : 1 a win pays ${num(e.odds)} and a loss costs 1,
        so 1 ÷ (1 + ${num(e.odds)}) = ${pct(a.breakeven)} is the chance you need to come out level.
        The true chance is ${num(Math.abs(gap), 2)} points ${gap >= 0 ? 'above' : 'below'} it.</li>
      <li><strong>3 · Edge (EV per unit): ${signed(a.ev)}.</strong> ${num(a.p, 4)} × ${num(e.odds)} − ${num(1 - a.p, 4)} = ${num(a.ev, 4)}.
        Over many repeats, every 100 staked ${good ? 'earns' : 'loses'} about ${num(Math.abs(a.ev) * 100, 1)} on average.</li>
      <li><strong>4 · Price: fair odds are ${num(a.fair_odds, 2)} : 1.</strong> Fair odds = (1 − p) ÷ p, the price where the bet has zero edge. ${price}</li>
      <li><strong>5 · Size: ${good ? num(stake) + ' u' : '0 u'}.</strong> ${size}</li>
    </ol>
    <p class="tiny muted">Half-Kelly here treats this bet in isolation. After you lock in, the review shows a joint plan for the whole board.</p>
    <p class="note-verdict ${good ? 'good' : 'bad'}"><strong>Verdict: ${good ? 'good buy' : 'not a buy'}.</strong>
      The true probability (${pct(a.p)}) ${good ? 'beats' : 'does not clear'} the ${pct(a.breakeven)} break-even at this price.</p>
  </div>`;
}

function hintContent(e, level) {
  const a = e.answer;
  const steps = [];
  if (level >= 1) steps.push(`<p class="hint-step"><strong>Approach.</strong> ${esc(a.nudge)}</p>`);
  if (level >= 2) {
    steps.push(`<p class="hint-step"><strong>Method.</strong> ${esc(a.method)} ${esc(a.tip)}
      Then compare with break-even: 1 ÷ (1 + ${num(e.odds)}) = ${pct(a.breakeven)}.</p>`);
  }
  if (level >= 3) steps.push(walkthrough(e));
  return steps.join('');
}

export function hintLadder(e) {
  return `<div class="hint-ladder" data-hints="${e.id}"><div class="hint-body"></div>
    <button type="button" class="small" data-hint-next="${e.id}">${HINT_BUTTONS[0]}</button></div>`;
}

/** Wire the hint buttons on a freshly drawn coach board. Each click opens one more step. */
export function wireHints(events) {
  app.hints = {};
  document.querySelectorAll('[data-hint-next]').forEach(button => {
    const e = events.find(x => x.id === button.dataset.hintNext);
    button.onclick = () => {
      const level = (app.hints[e.id] || 0) + 1;
      app.hints[e.id] = level;
      button.closest('.hint-ladder').querySelector('.hint-body').innerHTML = hintContent(e, level);
      if (level >= 3) button.remove();
      else button.textContent = HINT_BUTTONS[level];
    };
  });
}

// ---- Round reveal

export function lessonCards(list) {
  const eyebrow = { bad: 'Fix this', good: 'Well done', tip: 'Strategy' };
  return list
    .map(
      l => `<div class="lesson ${esc(l.tone)}"><div class="eyebrow">${eyebrow[l.tone] || 'Note'}</div>
      <h3>${esc(l.title)}</h3><p>${esc(l.body)}</p></div>`,
    )
    .join('');
}

function debrief(r) {
  const c = r.coaching;
  const rows = r.events
    .map(
      e => `<tr><td>${esc(e.label)}</td><td class="mono">${num(e.odds)} : 1</td><td class="mono">${num(e.fair_odds, 2)} : 1</td>
      <td class="mono">${num(e.coach.clear_odds, 2)} : 1</td><td>${esc(KIND_LABEL[e.coach.kind])}</td>
      <td class="mono">${num(e.stake)}</td><td class="mono">${num(e.coach.suggested_stake)}</td></tr>`,
    )
    .join('');
  return `<section class="debrief">
    <div class="eyebrow">COACH DEBRIEF</div>
    <h3>${esc(c.headline)}</h3>
    ${lessonCards(c.lessons)}
    <div class="plan-table review-table"><table>
      <thead><tr><th>Proposition</th><th>Offered</th><th>Fair price</th><th>Clear buy</th><th>Verdict</th><th>You staked</th><th>Suggested</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="plan-note">Your bets: expected profit ${signed(r.expected_profit)}, ${pct(r.loss_probability)} chance of a loss.
      Suggested plan: expected profit ${signed(c.plan_expected)}, worst case ${signed(c.plan_worst)}, ${pct(c.plan_loss_probability)} chance of a loss.
      Suggested stakes are half of the exact joint Kelly amount, so they account for the bets sharing one outcome.
      A clear buy pays 10% more profit odds than the fair price.</p>
  </section>`;
}

function headline(r) {
  if (r.staked === 0) {
    return [
      'You passed this board.',
      r.events.some(e => e.ev > 0)
        ? 'There were positive-EV opportunities. Check whether you recognised them, and whether uncertainty or combined risk justified passing.'
        : 'No positive-EV bets were available. Passing preserved your bankroll.',
    ];
  }
  if (r.expected_profit > 0) {
    return [
      'Positive expected value on this board.',
      r.profit < 0
        ? 'A positive-EV decision can lose. Evaluate the probability and exposure before changing your process.'
        : 'The outcome was profitable; the positive expected value is the more useful part of the decision.',
    ];
  }
  if (r.expected_profit < 0) {
    return [
      'This board cost you expected value.',
      r.profit > 0
        ? 'A profitable result does not repair negative expected value. Recheck the odds.'
        : 'Recheck probability against the break-even threshold before committing money.',
    ];
  }
  return [
    'This board was fair in expectation.',
    'A zero-EV position earns nothing on average. Check why you committed capital.',
  ];
}

function said(e) {
  const typed = app.lastTyped[e.id];
  return (typed && typed.includes('/') ? esc(typed) + ' = ' : '') + num(e.estimate, 2) + '%';
}

function propositionCard(e, r) {
  const badge =
    e.stake > 0
      ? e.ev > 1e-9
        ? 'POSITIVE EV'
        : e.ev < -1e-9
          ? 'NEGATIVE EV'
          : 'FAIR BET'
      : e.ev > 1e-9
        ? 'EDGE PASSED'
        : 'PASS';
  const badgeClass = e.stake > 0 && e.ev < 0 ? 'bad' : e.stake === 0 ? 'neutral' : '';
  const estimate =
    e.estimate === null
      ? '<p class="tiny muted">No estimate was entered before the deadline.</p>'
      : `<p class="tiny ${e.within_range ? 'positive' : 'negative'}"><strong>${e.within_range ? '✓ Accepted' : '✗ Outside the accepted range'}</strong>
        · You said ${said(e)}, the true probability is ${pct(e.p)} · error ${num(e.error_pp)} pts (accepted: within ±${r.tolerance}).</p>`;
  return `<article class="review-card">
    <div class="row spread"><h3>${esc(e.label)}</h3><span class="badge ${badgeClass}">${badge}</span></div>
    <div class="review-metrics">
      <div><span>TRUE PROBABILITY</span><strong>${pct(e.p)}</strong></div>
      <div><span>BREAK-EVEN</span><strong>${pct(e.breakeven)}</strong></div>
      <div><span>EV / UNIT</span><strong class="${e.ev < 0 ? 'negative' : 'positive'}">${signed(e.ev)}</strong></div>
      <div><span>STAKE → PROFIT</span><strong>${num(e.stake)} → ${signed(e.profit)}</strong></div>
    </div>
    <p class="coach-line ${esc(e.coach.kind)}">${esc(e.coach.verdict)}</p>
    ${estimate}
    <details><summary>Show the maths &amp; sizing reference</summary>
      <p>${esc(e.explanation.method)}</p>
      <p><strong>${esc(e.explanation.counting)}</strong></p>
      <p>${esc(e.explanation.tip)}</p>
      <div class="formula">${num(e.p, 4)} × ${num(e.odds)} − ${num(1 - e.p, 4)} = ${num(e.ev, 4)}</div>
      <p>Fair profit odds: ${num(e.fair_odds, 3)} : 1. Offered: ${num(e.odds)} : 1.</p>
      <p>Isolated half-Kelly reference: ${num(r.bank_before * e.kelly * 0.5)} units (${pct(e.kelly * 0.5)} of the opening bankroll).
        This is not a joint optimum for correlated bets.</p>
      <p>Event ${e.won ? 'occurred' : 'did not occur'}. ${e.stake > 0 ? (e.won ? 'Profit = stake × quoted profit odds.' : 'Loss = stake.') : 'No stake, so no profit or loss.'}</p>
    </details>
  </article>`;
}

const DIE_FACES = ['', '⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];

/** Draw the reveal for a settled round. `onNext` runs when the player continues. */
export function renderReview(r, onNext) {
  $('roundView').classList.add('hidden');
  $('reviewView').classList.remove('hidden');
  $('sessionTitle').textContent = 'Review the decision.';
  const dice = r.token_style === 'dice';
  const tokens = r.outcome
    .map((x, i) => {
      const cls = [
        'token',
        dice ? 'dice' : '',
        r.outcome_red[i] ? 'red' : '',
        String(x).length > 2 ? 'small' : '',
      ].join(' ');
      return `<div class="${cls}">${dice ? DIE_FACES[x] : esc(x)}</div>`;
    })
    .join('');
  const [verdict, feedback] = headline(r);
  const negative = r.events.filter(e => e.stake > 0 && e.ev < 0);
  const worstFraction = r.bank_before ? Math.max(0, -r.worst) / r.bank_before : 0;
  const warnings = [
    r.timed_out ? 'The deadline passed before this request arrived. All stakes were treated as passes.' : '',
    negative.length
      ? `${negative.length} negative-EV bet${negative.length > 1 ? 's' : ''} taken. Expected cost: ${num(r.negative_ev)} units. Compare each probability with its break-even threshold.`
      : '',
    worstFraction > 0.3
      ? `Combined risk: these bets could lose ${pct(worstFraction)} of your opening bankroll together. Isolated Kelly fractions do not account for this overlap.`
      : '',
  ].filter(Boolean);

  $('reviewView').innerHTML = `
    <div class="result-hero">
      <div class="row spread">
        <div>
          <div class="eyebrow">ROUND ${r.round} / THE REVEAL</div>
          <div class="result-tokens">${tokens}</div>
          <p>${esc(r.outcome_note)}</p>
        </div>
        <div style="text-align:right">
          <div class="profit-big ${r.profit < 0 ? 'loss' : ''}">${signed(r.profit)}</div>
          <p>realised profit · units</p>
        </div>
      </div>
      <h3>${verdict}</h3>
      <p>${feedback}</p>
    </div>
    ${warnings.map(w => `<div class="warning">${w}</div>`).join('')}
    <div class="metrics-mini four">
      <div><span>Expected profit</span><strong class="${r.expected_profit < 0 ? 'negative' : 'positive'}">${signed(r.expected_profit)}</strong></div>
      <div><span>Worst-case profit</span><strong>${signed(r.worst)}</strong></div>
      <div><span>Chance of a loss</span><strong>${pct(r.loss_probability)}</strong></div>
      <div><span>Estimates in range</span><strong>${r.estimates_in_range} / ${r.events.length}</strong></div>
    </div>
    ${debrief(r)}
    ${r.events.map(e => propositionCard(e, r)).join('')}
    <details style="margin:15px 0"><summary>See the exact distribution of ${esc(r.dist_label)}</summary>
      <p>The highlighted bar is this round’s realised value. Probabilities count every equally likely outcome.</p>
      ${histogram(r.distribution, r.dist_value, r.dist_label)}
    </details>
    <div class="submit-bar"><span class="keyboard"><kbd>Space</kbd> continue</span>
      <button class="primary" id="nextBtn">${app.session.finished ? 'View session report' : 'Next round ↗'}</button></div>`;
  $('nextBtn').onclick = onNext;
  $('committed').textContent = num(r.staked);
  $('cash').textContent = num(r.bank_before - r.staked);
  $('exposureNote').textContent = 'Last board: exact best-case profit ' + signed(r.best) + ' units.';
  window.scrollTo({ top: 0, behavior: 'instant' });
}

// ---- Session report

export function renderSummary(s, onAgain) {
  const errors = s.mean_error_pp === null ? 'No estimates entered' : num(s.mean_error_pp) + ' percentage points';
  const process =
    s.bets === 0
      ? 'No bets placed'
      : s.negative_ev_stake_pct > 0
        ? 'Reduce negative-EV exposure'
        : 'All staked money avoided negative-EV bets';
  const advice =
    s.mode === 'coach'
      ? 'Coach results may use hints. Switch to Interview or Targeted practice to measure unaided performance.'
      : s.mean_seconds > 70
        ? 'Practise recognising complements and counting small sample spaces before increasing the time pressure.'
        : 'Keep explaining why a price is favourable before deciding how much to commit.';
  const journal = s.history
    .map(
      r => `<tr><td>${r.round}</td><td>${esc(r.title)}</td><td>${num(r.staked)}</td>
      <td class="${r.expected_profit < 0 ? 'negative' : 'positive'}">${signed(r.expected_profit)}</td>
      <td>${signed(r.profit)}</td><td>${num(r.bank_after)}</td></tr>`,
    )
    .join('');
  const focus =
    s.focus && s.focus.labels && s.focus.labels.length
      ? `<div class="practice-note"><strong>This practice targeted:</strong><ul>${s.focus.labels.map(l => `<li>${esc(l)}</li>`).join('')}</ul>
        Your dashboard re-checks these patterns with every completed session.</div>`
      : '';

  $('summaryView').innerHTML = `
    <div class="session-top">
      <div>
        <div class="eyebrow muted">${s.abandoned ? 'SESSION ENDED EARLY' : 'SESSION COMPLETE'} / ${esc(s.mode.toUpperCase())}</div>
        <h1 style="font-size:42px;margin-top:10px">Measure the process.</h1>
        <p class="muted">${s.rounds} rounds · ${esc(s.difficulty)} · Seed <span class="mono">${esc(s.seed)}</span></p>
      </div>
      <button id="againBtn" class="primary">New session ↗</button>
    </div>
    ${s.abandoned ? '<div class="warning">You ended this session early, so it is not saved to your dashboard or your answer history. Finish every round (or let the sprint clock run out) for a session to count.</div>' : ''}
    ${focus}
    <div class="stats">
      <div class="stat"><span>Closing bankroll</span><strong>${num(s.bank)}</strong><small>Started at ${num(s.start_bank)}</small></div>
      <div class="stat"><span>Realised P&amp;L</span><strong class="${s.profit < 0 ? 'negative' : 'positive'}">${signed(s.profit)}</strong><small>Includes outcome luck</small></div>
      <div class="stat"><span>Cumulative EV</span><strong class="${s.expected_profit < 0 ? 'negative' : 'positive'}">${signed(s.expected_profit)}</strong><small>Expected profit of chosen stakes</small></div>
      <div class="stat"><span>Average decision</span><strong>${num(s.mean_seconds, 1)}s</strong><small>Per settled board</small></div>
    </div>
    <div class="summary-grid">
      <div class="summary-panel">
        <h3>Bankroll through the session</h3>
        ${lineChart(s.path)}
        <div class="chart-label"><span>Start · ${num(s.start_bank)}</span><span>Round ${s.rounds} · ${num(s.bank)}</span></div>
        <p class="tiny muted" style="margin:18px 0 0">Maximum drawdown: ${pct(s.max_drawdown)}. This chart shows outcomes, not decision quality.</p>
      </div>
      <div class="summary-panel">
        <h3>${process}</h3>
        <div class="side-item"><span>Money on negative-EV bets</span><strong>${s.negative_ev_stake_pct === null ? 'No stakes' : num(s.negative_ev_stake_pct) + '%'}</strong></div>
        <div class="side-item"><span>Positive-EV bets taken</span><strong>${s.positive_bets} / ${s.bets}</strong></div>
        <div class="side-item"><span>Available edges taken</span><strong>${s.edges_taken} / ${s.edges_available}</strong></div>
        <p class="tiny muted">Taking every edge is not the goal when bets overlap or your estimates are uncertain.</p>
        <div class="side-item"><span>Estimates within ±${s.tolerance} pts</span><strong>${s.estimates_in_range} / ${s.estimates_total}</strong></div>
        <div class="side-item"><span>Mean probability error</span><strong>${errors}</strong></div>
        <p class="tiny muted">${advice}</p>
      </div>
    </div>
    <div class="summary-panel"><h3>Profit and loss by round</h3>
      ${pnlChart(s.history.map(r => ({ pnl: r.profit, ev: r.expected_profit, label: 'Round ' + r.round })))}</div>
    <div class="summary-panel"><h3>Your training plan</h3>
      ${lessonCards(s.coaching.focus) || '<p class="muted">Complete a round to get coaching.</p>'}</div>
    <div class="summary-panel">
      <div class="row spread"><h3>Round journal</h3><button id="exportBtn" class="small">Export detailed CSV ↓</button></div>
      <div class="review-table"><table>
        <thead><tr><th>Round</th><th>Event</th><th>Staked</th><th>Expected profit</th><th>Actual profit</th><th>Bankroll</th></tr></thead>
        <tbody>${journal || '<tr><td colspan="6">No rounds completed.</td></tr>'}</tbody></table></div>
    </div>
    <details><summary>How to interpret these numbers</summary>
      <p>Cumulative EV sums the exact expected profits of stakes at the time you chose them. It is not a forecast of your next session
        or a strategy-optimal score. Mean error measures probability estimates you entered; missing estimates are excluded.
        All probability calculations enumerate every valid outcome.</p>
      <p>The single-bet Kelly formula assumes an isolated wager and a log-wealth objective. It is not the correct joint allocation for
        bets sharing the same outcome, which is why the debrief reports joint downside and joint Kelly stakes.</p>
    </details>`;
  $('againBtn').onclick = onAgain;
  $('exportBtn').onclick = () =>
    download('/api/export', { id: s.id || app.session.id }, 'edge-lab-session.csv').catch(err => toast(err.message));
}
