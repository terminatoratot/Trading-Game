// Trading game page: settings, the market-making table against three bots, and the results screen.
// The server deals the cards and runs the bots, so hidden cards never reach this page before the reveal.

import { $, api, clock, esc, num, signed, store, toast } from './util.js';

const SETTINGS = 'edge-lab-trading-settings';
const HISTORY = 'edge-lab-trading';
const PRESETS = {
  easy: { cards: 4, shown: 2, rounds: 6, seconds: 30, min: 2, max: 6, show: 'on' },
  medium: { cards: 4, shown: 1, rounds: 6, seconds: 20, min: 2, max: 5, show: 'on' },
  hard: { cards: 5, shown: 1, rounds: 8, seconds: 15, min: 1, max: 4, show: 'off' },
};
const DIFF_NOTES = {
  easy: 'Market events only change which cards can be dealt: even cards only, no face cards, high cards only. Two cards start face up.',
  medium:
    'Events change how the hand settles (aces low, the highest card counts double) or bring conditional news about hidden cards.',
  hard: 'Caps and floors, red minus black, stacked events and an insider bot. Five cards, tighter spreads, a faster clock, and you track your balance yourself.',
  custom: 'Your own table. Choose the market event level separately.',
};
const ORDINAL = ['', '1st', '2nd', '3rd', '4th'];
const VALUES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'];
// Chart marks: validated with the dataviz palette checker against the dark panel (#2a2624).
const PROFIT = '#2f9a6a';
const LOSS = '#d9542f';
const FIELDS = {
  tgCards: 'cards',
  tgShown: 'shown',
  tgRounds: 'rounds',
  tgSeconds: 'seconds',
  tgMin: 'min',
  tgMax: 'max',
  tgShow: 'show',
};

let difficulty = 'medium';
let game = null; // latest state from the server
let busy = false;
let deadline = null; // wall-clock ms when the decision clock runs out
let outcryStart = null; // wall-clock ms when the open-outcry race began
let ticker = null;
let pollHandle = null;
let actionKey = null; // which form is showing, so polling never wipes what you are typing
let revealed = []; // which cards were face up at the last draw, to animate flips
let saved = null; // id of the game already written to local history
let chartView = 'last';

// ---------------------------------------------------------------- settings

function setDifficulty(value, applyPreset = true) {
  difficulty = value;
  document.querySelectorAll('[data-diff]').forEach(b => {
    b.classList.toggle('on', b.dataset.diff === value);
    b.setAttribute('aria-checked', String(b.dataset.diff === value));
  });
  document.querySelectorAll('.custom-only').forEach(el => el.classList.toggle('hidden', value !== 'custom'));
  $('tgDiffNote').textContent = DIFF_NOTES[value];
  if (value !== 'custom' && applyPreset) {
    const preset = PRESETS[value];
    for (const [id, key] of Object.entries(FIELDS)) $(id).value = String(preset[key]);
    $('tgTier').value = value;
  }
  limitShown();
}

function limitShown() {
  const cards = Number($('tgCards').value);
  [...$('tgShown').options].forEach(o => (o.disabled = Number(o.value) >= cards));
  if (Number($('tgShown').value) >= cards) $('tgShown').value = String(cards - 1);
}

function readSettings() {
  return {
    difficulty,
    tier: difficulty === 'custom' ? $('tgTier').value : difficulty,
    mode: $('tgMode').value,
    cards: $('tgCards').value,
    shown: $('tgShown').value,
    rounds: $('tgRounds').value,
    seconds: $('tgSeconds').value,
    min_spread: $('tgMin').value,
    max_spread: $('tgMax').value,
    budget: $('tgBudget').value,
    events: $('tgEvents').value === 'on',
    check: $('tgCheck').value === 'on',
    track: $('tgShow').value === 'off',
    name: $('tgName').value.trim(),
    show: $('tgShow').value,
  };
}

function restoreSettings() {
  const s = store.get(SETTINGS, null);
  if (!s) return setDifficulty('medium');
  setDifficulty(s.difficulty || 'medium', false);
  const values = {
    tgTier: s.tier,
    tgMode: s.mode,
    tgCards: s.cards,
    tgShown: s.shown,
    tgRounds: s.rounds,
    tgSeconds: s.seconds,
    tgMin: s.min_spread,
    tgMax: s.max_spread,
    tgBudget: s.budget,
    tgShow: s.show,
    tgEvents: s.events === false ? 'off' : 'on',
    tgCheck: s.check === false ? 'off' : 'on',
    tgName: s.name,
  };
  for (const [id, v] of Object.entries(values)) if (v !== undefined && v !== null && $(id)) $(id).value = String(v);
  limitShown();
}

// ---------------------------------------------------------------- talking to the server

async function start(event) {
  if (event) event.preventDefault();
  if (busy) return;
  const settings = readSettings();
  if (Number(settings.max_spread) < Number(settings.min_spread))
    return toast('Max spread must be at least the min spread.');
  store.set(SETTINGS, settings);
  setBusy(true);
  $('tgStart').disabled = true;
  try {
    game = await api('/api/trade/start', settings);
    revealed = [];
    actionKey = null;
    show('tgGame');
    draw();
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(false);
    $('tgStart').disabled = false;
  }
}

let sent = 0; // requests sent, so a slow reply can never overwrite a newer one
let shown = 0;

async function act(action, extra = {}, { quiet = false } = {}) {
  if (!game || busy) return; // background polls also wait for your own actions
  if (!quiet) setBusy(true);
  const mine = ++sent;
  try {
    const state = await api('/api/trade/act', { id: game.id, action, ...extra });
    if (mine < shown || !game) return;
    shown = mine;
    game = state;
    draw();
  } catch (err) {
    if (!quiet) toast(err.message);
    if (/unavailable/.test(err.message)) backToSetup();
  } finally {
    if (!quiet) setBusy(false);
  }
}

function setBusy(value) {
  busy = value;
  $('tgGame').querySelector('.tg-board').classList.toggle('busy', value);
}

function show(id) {
  for (const s of ['tgSetup', 'tgGame', 'tgFinal']) $(s).classList.toggle('hidden', s !== id);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---------------------------------------------------------------- the table

function cardFace(c, flip) {
  if (!c.up) return '<div class="tg-card down" aria-label="Face-down card"></div>';
  const value = c.label.slice(0, -1);
  const suit = c.label.slice(-1);
  const centre = ['J', 'Q', 'K'].includes(value)
    ? `<div class="tg-face">${value}<small>${suit}</small></div>`
    : `<div class="tg-pip">${suit}</div>`;
  return `<div class="tg-card up ${c.red ? 'red' : ''} ${flip ? 'flip' : ''}" aria-label="${esc(c.label)}">
    <div class="tg-corner">${value}<small>${suit}</small></div>${centre}<div class="tg-corner br">${value}<small>${suit}</small></div></div>`;
}

const settled = r => r.phase === 'check' || r.phase === 'result';
const quoteText = q => `${q[0]} at ${q[1]}`;

function playerCard(p, i) {
  const r = game.round;
  const isMaker = r && r.maker === i;
  const tag = p.you ? '<span class="tg-tag you">You</span>' : '<span class="tg-tag">Bot</span>';
  let middle = '';
  if (!r) {
    middle = '<span class="tg-wait">Market closed</span>';
  } else if (isMaker) {
    const q = r.quote;
    middle = `<span class="tg-mm">Market Maker</span>
      <div class="tg-quote"><div><small>BID</small><b>${q ? q[0] : '–'}</b></div><div><small>ASK</small><b>${q ? q[1] : '–'}</b></div></div>`;
  } else if (r.phase === 'outcry') {
    middle = p.you ? '<span class="tg-thinking">Shout a quote</span>' : '<span class="tg-wait">Ready to shout…</span>';
  } else if (settled(r)) {
    const index = r.result.trades.findIndex(t => t.player === i);
    const t = r.result.trades[index];
    const line = t ? `${t.side === 'buy' ? 'Bought' : 'Sold'} ${t.size} @ ${t.price}` : 'Passed';
    middle = `<span class="tg-trade-line" style="--i:${index < 0 ? 0 : index}">${line}</span>`;
  } else if (p.you) {
    middle = '<span class="tg-thinking">Your move</span>';
  } else if (r.maker === 0) {
    middle = '<span class="tg-wait">Waiting for your quote</span>';
  } else {
    middle = '<span class="tg-ok" title="Ready">✓</span>';
  }
  const hidden = p.score === null;
  let delta = '';
  if (r && r.phase === 'result' && r.result.pnl && !hidden) {
    const pnl = i === 0 && r.check ? r.check.credited : r.result.pnl[i];
    delta = ` <span class="tg-pnl-chip ${pnl < 0 ? 'negative' : 'positive'}">(${signed(pnl)})</span>`;
  }
  return `<div class="tg-player ${isMaker ? 'maker' : ''}">
    <div class="tg-player-name">${esc(p.name)} ${tag}</div>
    <div class="tg-style">${p.style ? esc(p.style) : '&nbsp;'}</div>
    <div class="tg-player-mid">${middle}</div>
    <div class="tg-score">Score: <b class="${hidden ? 'blurred' : ''}">${hidden ? '000' : num(p.score)}</b>${delta}</div>
  </div>`;
}

function outcryLine(r) {
  const o = r.outcry;
  if (!o) return '';
  if (o.winner === 0) return `You shouted first (${num(o.time, 1)}s), so you make the market. `;
  const who = game.players[o.winner].name;
  const late = o.your_time ? ` Your shout at ${num(o.your_time, 1)}s was too late.` : '';
  return `${esc(who)} shouted first (${num(o.time, 1)}s).${late} `;
}

function infoLine() {
  const r = game.round;
  if (r.phase === 'event') return 'Preparing the market…';
  if (r.phase === 'outcry')
    return 'Open outcry: shout a two-way quote. The first valid quote becomes the market maker.';
  const prefix = outcryLine(r);
  if (r.phase === 'decide') {
    return r.maker === 0
      ? `${prefix}You are the market maker. Quote X at Y with a spread of ${game.min_spread}–${game.max_spread} points.`
      : `${prefix}${esc(game.players[r.maker].name)} quotes <b>${quoteText(r.quote)}</b>: sell at ${r.quote[0]}, buy at ${r.quote[1]}, or pass.`;
  }
  if (r.result.timed_out)
    return r.maker === 0 ? 'Time ran out before you quoted, so nobody traded.' : 'Time ran out, so you passed.';
  if (r.maker === 0) {
    const n = r.result.trades.length;
    return `${prefix}You quoted ${quoteText(r.quote)}. ${n ? `${n} player${n === 1 ? '' : 's'} traded with you.` : 'Nobody traded with you.'}`;
  }
  const order = r.your_order;
  if (!order || order[0] === 'pass') return `${prefix}You passed on ${quoteText(r.quote)}.`;
  return `${prefix}You ${order[0] === 'buy' ? 'bought' : 'sold'} ${order[1]} unit${order[1] === 1 ? '' : 's'} at ${order[0] === 'buy' ? r.quote[1] : r.quote[0]}.`;
}

// ---------------------------------------------------------------- action panels

function quoteForm(shout) {
  return `<form id="tgQuoteForm" autocomplete="off">
    ${shout ? '<p class="tg-shout-note">Be quick: the bots are pricing the same cards.</p>' : ''}
    <div class="tg-quote-form">
      <label>BID (X)<input class="tg-input" id="tgBid" inputmode="numeric" placeholder="e.g. 30"></label>
      <label>ASK (Y)<input class="tg-input" id="tgAsk" inputmode="numeric" placeholder="e.g. 33"></label>
    </div>
    <div class="tg-preview" id="tgPreview">– at –<small>spread ${game.min_spread}–${game.max_spread} points</small></div>
    <div class="tg-actions-right"><button class="tg-btn" id="tgPost" disabled>${shout ? 'Shout quote ↵' : 'Post quote ↵'}</button></div>
  </form>`;
}

function tradeForm() {
  const r = game.round;
  const [bid, ask] = r.quote;
  const lim = r.limits;
  const most = Math.max(lim.buy, lim.sell, 1);
  const start = Math.min(5, most);
  return `<div class="tg-units">
      <label for="tgUnits">UNITS</label>
      <button type="button" class="tg-step" data-step="-1" aria-label="One fewer">−</button>
      <input id="tgUnits" inputmode="numeric" value="${start}" aria-label="Units">
      <button type="button" class="tg-step" data-step="1" aria-label="One more">+</button>
      ${[1, 5, 10]
        .filter(n => n <= most)
        .map(n => `<button type="button" class="tg-chip" data-units="${n}">${n}</button>`)
        .join('')}
      <button type="button" class="tg-chip" data-units="max">Max</button>
    </div>
    <div class="tg-trade-buttons">
      <button class="buy" data-side="buy" ${lim.buy ? '' : 'disabled'}>Buy at ${ask}<small>B · up to ${lim.buy} units</small></button>
      <button class="sell" data-side="sell" ${lim.sell ? '' : 'disabled'}>Sell at ${bid}<small>S · up to ${lim.sell} units</small></button>
      <button class="pass" data-side="pass">Pass<small>P</small></button>
    </div>
    <p class="tg-hint">Longs must be affordable (units × ask). Shorts must cover the worst case: the highest possible value minus the bid, per unit.</p>`;
}

function answerForm(id, question, hint) {
  return `<form id="${id}" autocomplete="off">
    <p class="tg-q">${question}</p>
    <input class="tg-input" id="tgAnswer" inputmode="numeric">
    <p class="tg-hint">${hint}</p>
    <div class="tg-actions-right"><button class="tg-btn" id="tgSubmitAnswer" disabled>Submit ↵</button></div>
  </form>`;
}

function feedbackPanel() {
  const r = game.round;
  const res = r.result;
  const fb = r.feedback;
  const yourPnl = r.check ? r.check.credited : res.pnl[0];
  const quote = r.quote ? quoteText(r.quote) : 'No quote';
  const trades = res.trades
    .filter(t => t.player !== 0)
    .map(t => `${esc(t.name)} ${t.side === 'buy' ? 'bought' : 'sold'} ${t.size} @ ${t.price}`);
  const check = r.check
    ? `<p class="tg-check-line ${r.check.correct ? 'positive' : 'negative'}">${
        r.check.correct
          ? `✓ Return reported correctly: ${signed(r.check.actual)}.`
          : `✗ You reported ${signed(r.check.answer)}; the return was ${signed(r.check.actual)}. ${r.check.actual > 0 ? 'Profit forfeited and ' : ''}${game.penalty} point penalty.`
      }</p>`
    : '';
  const extra = res.insider
    ? `<li>${esc(res.insider.name)} was the insider and had seen the ${esc(res.insider.card)}.</li>`
    : '';
  const notes =
    fb.notes.map(n => `<li>${esc(n)}</li>`).join('') + (fb.notes.some(n => n.includes('had seen')) ? '' : extra);
  const sample = res.exact
    ? `all ${num(res.hands, 0)} possible hidden hands`
    : `a sample of ${num(res.hands, 0)} hidden hands`;
  return `${check}
    <div class="tg-keyline">
      <div><span>${r.maker === 0 ? 'YOUR QUOTE' : 'QUOTE'}</span><b>${quote}</b></div>
      <div><span>FAIR VALUE</span><b>${num(res.fair, 1)}</b></div>
      <div><span>MARKET PRICE</span><b>${res.value}</b></div>
      <div><span>YOUR P&amp;L</span><b class="${yourPnl < 0 ? 'negative' : 'positive'}">${signed(yourPnl)}</b></div>
    </div>
    ${trades.length ? `<p class="tg-trades-line">${trades.join(' · ')}</p>` : ''}
    <div class="tg-verdict ${fb.tone}">
      <span aria-hidden="true">${fb.tone === 'good' ? '✓' : '!'}</span>
      <div class="lines">
        <h4>${esc(fb.title)}</h4>
        <p>${esc(fb.what)}</p>
        ${fb.better ? `<p class="tg-better"><b>Better play</b> · ${esc(fb.better.replace(/^Better: /, ''))}</p>` : ''}
        ${notes ? `<ul class="tg-notes">${notes}</ul>` : ''}
      </div>
    </div>
    ${mathPanel(r.math, sample, r.event, res.fair)}
    <div class="tg-actions-right"><button class="tg-btn" id="tgNext">${r.number === game.rounds ? 'See results ↵' : 'Continue ↵'}</button></div>`;
}

/** The worked derivation of fair value: plain words for each step, with the maths typeset by KaTeX. */
function mathPanel(math, sample, ev, fair) {
  if (!math) return '';
  const steps = math.steps
    .map(
      (st, i) => `<li><div class="tg-step-head"><span class="tg-step-n">${i + 1}</span><b>${esc(st.label)}</b></div>
      <p>${esc(st.words)}</p><div class="tg-tex" data-tex="${esc(st.tex)}"></div></li>`,
    )
    .join('');
  return `<section class="tg-math" aria-label="How fair value was worked out">
    <div class="tg-label">${ev ? 'HOW THE MARKET EVENT RESOLVES' : 'HOW FAIR VALUE IS WORKED OUT'}</div>
    <p class="tg-math-summary">${esc(math.summary)}</p>
    ${math.lesson ? `<p class="tg-math-lesson"><b>Intuition</b> · ${esc(math.lesson)}</p>` : ''}
    ${
      math.shortcut
        ? `<div class="tg-fast"><div class="tg-fast-head"><b>Fastest way</b><span>≈ ${num(math.shortcut.estimate, 1)} · exact ${num(fair, 2)}</span></div>
        <p>${esc(math.shortcut.words)}</p><div class="tg-tex" data-tex="${esc(math.shortcut.tex)}"></div></div>`
        : ''
    }
    <ol class="tg-steps">${steps}</ol>
    <p class="tg-hint">S is the sum of the card values. Probabilities and averages run over ${sample}.</p>
  </section>`;
}

/** Typeset every pending formula; fall back to the raw source if KaTeX did not load. */
function typeset(root) {
  root.querySelectorAll('.tg-tex').forEach(el => {
    if (window.katex) window.katex.render(el.dataset.tex, el, { displayMode: true, throwOnError: false });
    else el.textContent = el.dataset.tex;
  });
}

function renderAction() {
  const action = $('tgAction');
  if (game.awaiting_balance) {
    action.innerHTML = answerForm(
      'tgBalanceForm',
      'What is your final balance?',
      `You started with ${num(game.budget)} points. Exact answers only: a wrong answer costs ${game.penalty} points.`,
    );
  } else {
    const r = game.round;
    if (r.phase === 'outcry') action.innerHTML = quoteForm(true);
    else if (r.phase === 'decide') action.innerHTML = r.maker === 0 ? quoteForm(false) : tradeForm();
    else if (r.phase === 'check')
      action.innerHTML = answerForm(
        'tgCheckForm',
        'What was your profit or loss this round?',
        `Exact answers only: a wrong answer forfeits this round's profit and adds a ${game.penalty} point penalty. Use a minus sign (-) for losses.`,
      );
    else if (r.phase === 'result') action.innerHTML = feedbackPanel();
    else action.innerHTML = '';
  }
  action.classList.remove('enter');
  void action.offsetWidth; // restart the entrance animation
  action.classList.add('enter');
  typeset(action);
  wireAction();
}

function wireAction() {
  if ($('tgQuoteForm')) {
    const update = () => {
      const filled = $('tgBid').value.trim() !== '' && $('tgAsk').value.trim() !== '';
      const bid = Number($('tgBid').value);
      const ask = Number($('tgAsk').value);
      const spread = ask - bid;
      const ok =
        filled &&
        Number.isInteger(bid) &&
        Number.isInteger(ask) &&
        spread >= game.min_spread &&
        spread <= game.max_spread;
      $('tgPost').disabled = !ok;
      $('tgPreview').innerHTML = filled
        ? `${esc($('tgBid').value)} at ${esc($('tgAsk').value)}<small>${ok ? `spread ${spread} · mid ${num((bid + ask) / 2, 1)} ✓` : `spread must be ${game.min_spread}–${game.max_spread}, whole numbers`}</small>`
        : `– at –<small>spread ${game.min_spread}–${game.max_spread} points</small>`;
    };
    $('tgBid').oninput = update;
    $('tgAsk').oninput = update;
    $('tgQuoteForm').onsubmit = e => {
      e.preventDefault();
      if (!$('tgPost').disabled) act('quote', { bid: Number($('tgBid').value), ask: Number($('tgAsk').value) });
    };
    $('tgBid').focus({ preventScroll: true });
  }
  if ($('tgUnits')) {
    const lim = game.round.limits;
    const most = Math.max(lim.buy, lim.sell, 1);
    const set = n => {
      const value = Math.max(1, Math.min(most, n));
      $('tgUnits').value = String(value);
      document
        .querySelectorAll('[data-units]')
        .forEach(c => c.classList.toggle('on', c.dataset.units === String(value)));
      // A side is only clickable while the chosen size is affordable on that side.
      for (const side of ['buy', 'sell'])
        $('tgAction').querySelector(`[data-side="${side}"]`).disabled = value > lim[side];
    };
    document.querySelectorAll('[data-step]').forEach(b => (b.onclick = () => set(units() + Number(b.dataset.step))));
    document
      .querySelectorAll('[data-units]')
      .forEach(b => (b.onclick = () => set(b.dataset.units === 'max' ? most : Number(b.dataset.units))));
    $('tgUnits').onchange = () => set(units());
    document.querySelectorAll('[data-side]').forEach(b => (b.onclick = () => order(b.dataset.side)));
    set(units());
  }
  const answer = $('tgCheckForm') || $('tgBalanceForm');
  if (answer) {
    $('tgAnswer').oninput = () => ($('tgSubmitAnswer').disabled = !/^[+\-−]?[\d,]+$/.test($('tgAnswer').value.trim()));
    answer.onsubmit = e => {
      e.preventDefault();
      if (!$('tgSubmitAnswer').disabled)
        act(answer.id === 'tgCheckForm' ? 'answer' : 'balance', { answer: $('tgAnswer').value.trim() });
    };
    $('tgAnswer').focus({ preventScroll: true });
  }
  if ($('tgNext')) {
    $('tgNext').onclick = () => act('next');
    $('tgNext').focus({ preventScroll: true });
  }
}

const units = () => Math.max(1, parseInt($('tgUnits').value, 10) || 1);

function order(side) {
  if (side === 'pass') return act('order', { side });
  const limit = game.round.limits[side];
  if (units() > limit) return toast(`You can ${side} at most ${limit} units with your balance.`);
  act('order', { side, size: units() });
}

// ---------------------------------------------------------------- drawing

function draw() {
  if (game.finished) return drawFinal(game.summary);
  const r = game.round;
  $('tgRound').textContent = r ? `ROUND ${r.number} / ${game.rounds}` : 'MARKET CLOSED';
  $('tgPlayers').innerHTML = game.players.map(playerCard).join('');
  if (r) {
    $('tgHand').innerHTML = r.cards.map((c, i) => cardFace(c, c.up && revealed.length && !revealed[i])).join('');
    revealed = r.cards.map(c => c.up);
  } else {
    $('tgHand').innerHTML = '';
  }
  $('tgEventChip').classList.toggle('hidden', !r || !r.event || r.phase === 'event');
  $('tgEventChip').textContent = r && r.event ? '⚠ ' + r.event.text : '';
  $('tgInfo').innerHTML = `<span class="i">i</span><span>${
    r ? infoLine() : 'All rounds are done. You kept track of your balance: report it to close the market.'
  }</span>`;
  const you = game.players[0];
  $('tgBank').textContent = you.score === null ? '000' : num(you.score);
  $('tgBank').classList.toggle('blurred', you.score === null);

  // Only rebuild the action panel when the decision changes, never mid-typing.
  const key = game.awaiting_balance ? 'balance' : `${r.number}:${r.phase}:${r.maker}`;
  if (key !== actionKey) {
    actionKey = key;
    renderAction();
  }

  $('tgModal').classList.toggle('hidden', !r || r.phase !== 'event');
  if (r && r.phase === 'event') {
    $('tgModalText').textContent = r.event.text;
    setTimeout(() => $('tgBegin').focus(), 30);
  }
  syncClocks(r);
}

function syncClocks(r) {
  clearInterval(ticker);
  clearInterval(pollHandle);
  deadline = r && r.remaining !== null && r.remaining !== undefined ? Date.now() + r.remaining * 1000 : null;
  outcryStart = r && r.phase === 'outcry' ? Date.now() - r.elapsed * 1000 : null;
  if (outcryStart !== null) pollHandle = setInterval(() => act('state', {}, { quiet: true }), 400);
  tick();
  if (deadline !== null || outcryStart !== null) ticker = setInterval(tick, 200);
}

function tick() {
  if (!game || game.finished) return;
  const r = game.round;
  if (outcryStart !== null) {
    $('tgClock').textContent = '📣 ' + clock((Date.now() - outcryStart) / 1000);
    $('tgClock').classList.remove('urgent');
    return;
  }
  if (deadline === null) {
    $('tgClock').textContent = r && r.phase === 'decide' ? 'No clock' : '';
    return;
  }
  const left = (deadline - Date.now()) / 1000;
  $('tgClock').textContent = '⏱ ' + clock(left);
  $('tgClock').classList.toggle('urgent', left < 6);
  // Past the server's grace period: ask it to settle the round (a pass, or no quote), and keep asking.
  if (left <= -2.5 && !busy) {
    deadline = Date.now();
    act('state');
  }
}

// ---------------------------------------------------------------- results

function drawFinal(s) {
  clearInterval(ticker);
  clearInterval(pollHandle);
  $('tgModal').classList.add('hidden');
  if (saved !== game.id) {
    saved = game.id;
    const list = store.get(HISTORY, []);
    list.push({ at: Date.now(), profit: s.profit, place: s.place, difficulty: s.difficulty });
    store.set(HISTORY, list.slice(-200));
  }
  const medal = i => `<span class="tg-medal m${i + 1}">${i + 1}</span>`;
  const rows = s.history
    .map(
      h => `<tr><td class="num">${h.round}</td><td>${h.maker === 0 ? 'Maker' : 'Taker'}</td><td>${h.event ? esc(h.event) : '–'}</td>
      <td class="num">${num(h.fair, 1)}</td><td class="num">${h.value}</td>
      <td class="num ${h.pnl < 0 ? 'negative' : 'positive'}">${signed(h.pnl)}</td><td>${h.check === null ? '–' : h.check ? '✓' : '✗'}</td></tr>`,
    )
    .join('');
  const fc = s.final_check;
  const balanceLine = fc
    ? `<p class="${fc.correct ? 'positive' : 'negative'}">${fc.correct ? '✓' : '✗'} Final balance reported as ${num(fc.answer)}; it was ${num(fc.actual)}.${
        fc.correct ? '' : ` ${game.penalty} point penalty.`
      }</p>`
    : '';
  $('tgFinal').innerHTML = `
    <div class="tg-panel tg-closed">
      <div class="tg-kicker">MARKET CLOSED</div>
      <h1 class="tg-title">Trading Game</h1>
      <div class="tg-big ${s.profit < 0 ? 'negative' : 'positive'}">${signed(s.profit)}</div>
      <div class="tg-label">REALIZED P&amp;L · FINISHED ${ORDINAL[s.place].toUpperCase()}</div>
      <div class="tg-closed-tiles">
        <div class="tg-stat"><span>FINAL SCORE</span><strong>${num(s.score)}</strong></div>
        <div class="tg-stat"><span>STARTING BUDGET</span><strong>${num(s.budget)}</strong></div>
        <div class="tg-stat"><span>ROUNDS</span><strong>${s.rounds}</strong></div>
        <div class="tg-stat"><span>PLACE</span><strong>${ORDINAL[s.place]}</strong></div>
      </div>
      <div class="tg-closed-actions"><button class="tg-btn" id="tgAgain">Play Again</button>
        <button class="tg-btn ghost" id="tgChange">Change settings</button></div>
    </div>
    <div class="tg-panel tg-recap">
      <p>Your final balance after the last round was <b>${num(s.score)}</b> points.</p>
      <p>After subtracting your starting budget of <b>${num(s.budget)}</b> you realized a total profit of
        <b class="${s.profit < 0 ? 'negative' : 'positive'}">${signed(s.profit)}</b> points.</p>
      ${s.checked ? `<p>Returns reported correctly: <b>${s.checks} of ${s.checked}</b>.</p>` : ''}
      ${balanceLine}
      <hr class="tg-divider">
      <h3 class="tg-serif">Final Rankings</h3>
      ${s.rankings
        .map(
          (p, i) => `<div class="tg-rank ${p.you ? 'you' : ''}">${medal(i)}
          <div><b>${esc(p.name)}</b> ${p.you ? '<span class="tg-tag you">You</span>' : `<span class="tg-tag">${esc(p.style)}</span>`}
            <small>A ${p.profit < 0 ? 'loss' : 'profit'} of ${num(Math.abs(p.profit))} points</small></div>
          <b>${num(p.score)} pts</b></div>`,
        )
        .join('')}
      <hr class="tg-divider">
      <h3 class="tg-serif">Round by round</h3>
      <div style="overflow-x:auto"><table class="tg-rounds"><thead><tr><th>#</th><th>Role</th><th>Event</th><th>Fair</th><th>Price</th><th>Your P&amp;L</th><th>Return</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
    </div>`;
  $('tgAgain').onclick = () => start();
  $('tgChange').onclick = backToSetup;
  show('tgFinal');
}

function backToSetup() {
  clearInterval(ticker);
  clearInterval(pollHandle);
  game = null;
  actionKey = null;
  $('tgModal').classList.add('hidden');
  show('tgSetup');
  drawStats();
  drawLeaders();
}

// ---------------------------------------------------------------- statistics (this browser) and leaderboard (this server)

function chartPoints() {
  const list = store.get(HISTORY, []);
  if (chartView === 'last') {
    return list.slice(-10).map(g => ({
      value: g.profit,
      label: `${new Date(g.at).toLocaleDateString()} · ${signed(g.profit)} · ${ORDINAL[g.place]} · ${g.difficulty}`,
    }));
  }
  const days = new Map();
  for (const g of list) {
    const day = new Date(g.at).toLocaleDateString();
    days.set(day, (days.get(day) || []).concat(g.profit));
  }
  return [...days.entries()].slice(-10).map(([day, values]) => {
    const avg = values.reduce((a, b) => a + b, 0) / values.length;
    return {
      value: avg,
      label: `${day} · average ${signed(Number(avg.toFixed(1)))} over ${values.length} game${values.length === 1 ? '' : 's'}`,
    };
  });
}

function drawChart() {
  const points = chartPoints();
  if (!points.length) {
    $('tgChart').innerHTML = '<p class="tg-empty">Finish a game to start your chart.</p>';
    return;
  }
  const w = 560;
  const h = 200;
  const pad = 18;
  const values = points.map(p => p.value);
  const lo = Math.min(0, ...values);
  const range = Math.max(Math.max(0, ...values) - lo, 1);
  const X = i => pad + (points.length === 1 ? (w - 2 * pad) / 2 : (i / (points.length - 1)) * (w - 2 * pad));
  const Y = v => pad + (1 - (v - lo) / range) * (h - 2 * pad);
  const zero = Y(0);
  const line = points.map((p, i) => `${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(' ');
  const area = `${X(0)},${zero} ${line} ${X(points.length - 1)},${zero}`;
  const marks = points
    .map((p, i) => {
      const x = X(i);
      const y = Y(p.value);
      const shape =
        p.value >= 0
          ? `<circle cx="${x}" cy="${y}" r="5" fill="${PROFIT}" stroke="#2a2624" stroke-width="2"/>`
          : `<rect x="${x - 5}" y="${y - 5}" width="10" height="10" transform="rotate(45 ${x} ${y})" fill="${LOSS}" stroke="#2a2624" stroke-width="2"/>`;
      return `<g data-tip="${esc(p.label)}" tabindex="0" role="img" aria-label="${esc(p.label)}"><circle class="hit" cx="${x}" cy="${y}" r="14"/>${shape}</g>`;
    })
    .join('');
  $('tgChart').innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Profit per game">
      <defs><clipPath id="above"><rect x="0" y="0" width="${w}" height="${zero}"/></clipPath>
        <clipPath id="below"><rect x="0" y="${zero}" width="${w}" height="${h - zero}"/></clipPath></defs>
      <polygon points="${area}" fill="${PROFIT}" fill-opacity="0.18" clip-path="url(#above)"/>
      <polygon points="${area}" fill="${LOSS}" fill-opacity="0.18" clip-path="url(#below)"/>
      <line x1="${pad}" x2="${w - pad}" y1="${zero}" y2="${zero}" stroke="#4a433f" stroke-dasharray="4 5"/>
      <polyline points="${line}" fill="none" stroke="#a9a19a" stroke-width="2" stroke-linejoin="round"/>
      ${marks}
    </svg><div class="tg-chart-tip hidden"></div>
    <details><summary>Show as a table</summary><table><tbody>${points.map(p => `<tr><td>${esc(p.label)}</td></tr>`).join('')}</tbody></table></details>`;
  const tip = $('tgChart').querySelector('.tg-chart-tip');
  $('tgChart')
    .querySelectorAll('[data-tip]')
    .forEach(g => {
      const showTip = () => {
        const box = $('tgChart').getBoundingClientRect();
        const dot = g.getBoundingClientRect();
        tip.textContent = g.dataset.tip;
        tip.style.left = dot.left + dot.width / 2 - box.left + 'px';
        tip.style.top = dot.top - box.top + 'px';
        tip.classList.remove('hidden');
      };
      g.addEventListener('mouseenter', showTip);
      g.addEventListener('focus', showTip);
      g.addEventListener('mouseleave', () => tip.classList.add('hidden'));
      g.addEventListener('blur', () => tip.classList.add('hidden'));
    });
}

function drawStats() {
  const list = store.get(HISTORY, []);
  const best = list.length ? Math.max(...list.map(g => g.profit)) : null;
  const latest = list.length ? list[list.length - 1].profit : null;
  const tile = (label, value, money) =>
    `<div class="tg-stat"><span>${label}</span><strong class="${money && value !== null ? (value < 0 ? 'negative' : 'positive') : ''}">${
      value === null ? '–' : money ? signed(value) : value
    }</strong></div>`;
  $('tgStats').innerHTML =
    tile('SESSIONS', list.length, false) + tile('BEST SESSION', best, true) + tile('LATEST', latest, true);
  drawChart();
}

async function drawLeaders() {
  try {
    const { rows } = await api('/api/trade/leaderboard', {});
    $('tgLeaders').innerHTML = rows.length
      ? rows
          .map(
            (r, i) => `<div class="tg-leader"><span class="tg-medal m${i + 1}">${i + 1}</span><span>${esc(r.name)}
            <span class="tg-style">${r.games} game${r.games === 1 ? '' : 's'}</span></span>
            <b class="${r.profit < 0 ? 'negative' : 'positive'}">${signed(r.profit)}</b></div>`,
          )
          .join('')
      : '<p class="tg-empty">No named games yet. Add a leaderboard name in Settings to appear here; friends on the same link share this board.</p>';
  } catch (err) {
    $('tgLeaders').innerHTML = `<p class="tg-empty">${esc(err.message)}</p>`;
  }
}

// ---------------------------------------------------------------- wiring

$('tgValueRow').innerHTML = VALUES.map((v, i) => `<div class="tg-value-chip">${v}♠<small>${i + 2}</small></div>`).join(
  '',
);
document.querySelectorAll('[data-diff]').forEach(b => (b.onclick = () => setDifficulty(b.dataset.diff)));
for (const id of Object.keys(FIELDS))
  $(id).addEventListener('change', () => difficulty !== 'custom' && setDifficulty('custom', false));
$('tgCards').addEventListener('change', limitShown);
$('tgForm').onsubmit = start;
$('tgBegin').onclick = () => act('begin');
$('tgQuit').onclick = () => confirm('End this game? It will not be saved.') && backToSetup();
$('tgHowTo').addEventListener('toggle', () => store.set('edge-lab-trading-howto', $('tgHowTo').open));
if (store.get('edge-lab-trading-howto', true) === false) $('tgHowTo').open = false;
document.querySelectorAll('[data-view]').forEach(b => {
  b.onclick = () => {
    chartView = b.dataset.view;
    document.querySelectorAll('[data-view]').forEach(x => x.classList.toggle('on', x === b));
    drawChart();
  };
});
document.addEventListener('keydown', e => {
  if (!game || game.finished || busy || !game.round) return;
  const r = game.round;
  const typing =
    ['text', 'search'].includes(document.activeElement.type) || document.activeElement.inputMode === 'numeric';
  if (r.phase === 'event' && e.key === 'Enter') {
    e.preventDefault();
    act('begin');
  } else if (r.phase === 'decide' && r.maker !== 0 && $('tgUnits')) {
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      $('tgUnits').value = String(units() + (e.key === 'ArrowUp' ? 1 : -1));
      $('tgUnits').dispatchEvent(new Event('change'));
      return;
    }
    const side = { b: 'buy', s: 'sell', p: 'pass' }[e.key.toLowerCase()];
    if (side && !(typing && document.activeElement.id !== 'tgUnits')) {
      e.preventDefault();
      order(side);
    }
  }
});
window.addEventListener('beforeunload', e => {
  if (game && !game.finished) {
    e.preventDefault();
    e.returnValue = '';
  }
});

restoreSettings();
drawStats();
drawLeaders();
