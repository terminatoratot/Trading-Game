// Single-player sessions: the setup form, drawing a board, reading bets, timers, settling and finishing.

import { app } from './state.js';
import {
  answerLog,
  commitAnswers,
  discardAnswers,
  entriesFromRound,
  holdAnswers,
  profile,
  renderDashboard,
  saveSummary,
} from './history.js';
import { hintLadder, renderReview, renderSummary, wireHints } from './review.js';
import { createRoom, leaveRoom, roomNext, submitRoom } from './rooms.js';
import { startDrill } from './drill.js';
import {
  $,
  api,
  boardGraphic,
  clock,
  describeTyped,
  esc,
  num,
  parseProb,
  plural,
  screen,
  signed,
  toast,
} from './util.js';

const START_LABEL = { room: 'Create room ↗', drill: 'Start drill ↗', practice: 'Start targeted practice ↗' };
const HINTS = {
  practice: 'Boards are chosen from your answer history. Answers stay hidden until you lock your bets.',
  drill: 'One question at a time. Type a percentage or a fraction and press Enter; the clock does not stop.',
  room: 'Create a room and share the link, or join a friend below.',
};
const DEFAULT_HINT =
  'All money is imaginary. One shared roll or draw settles the whole board. You may bet on several events, or pass on every event.';

// ---- Setup

export function setMode(value) {
  app.mode = value;
  document.querySelectorAll('[data-mode]').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === value);
    b.setAttribute('aria-pressed', String(b.dataset.mode === value));
  });
  document.querySelectorAll('#configForm [data-for]').forEach(field => {
    field.classList.toggle('hidden', !field.dataset.for.split(' ').includes(value));
  });
  const multi = value === 'room';
  $('joinPanel').classList.toggle('hidden', !multi);
  document.querySelectorAll('.room-only').forEach(option => (option.hidden = !multi));
  if (!multi && $('seconds').value === '0') $('seconds').value = '60';
  $('startBtn').textContent = START_LABEL[value] || 'Start session ↗';
  $('configHint').textContent = HINTS[value] || DEFAULT_HINT;
  showPracticeNote();
}

/** Tell the player what targeted practice will focus on, or why it cannot yet. */
export function showPracticeNote() {
  const note = $('practiceNote');
  const pr = profile();
  const show = app.mode === 'practice' || (app.mode === 'drill' && $('drillTargeted').checked);
  note.classList.toggle('hidden', !show);
  if (!show) return;
  if (!pr || !pr.ready) {
    const have = pr ? pr.estimates : 0;
    const need = pr ? pr.need : 12;
    note.innerHTML = `<strong>Not enough history yet.</strong> Targeting needs ${need} answered questions from completed sessions
      (you have ${have}). Until then you get a general mix, and every answer still counts toward your profile.`;
  } else if (!pr.issues.length) {
    note.innerHTML = '<strong>No clear weaknesses found.</strong> You will get a general mix; try a harder difficulty.';
  } else {
    note.innerHTML = `<strong>Focusing on:</strong><ul>${pr.issues
      .slice(0, 3)
      .map(i => `<li>${esc(i.title)}</li>`)
      .join('')}</ul>`;
  }
}

function formValues(ids) {
  const values = {};
  for (const id of ids) values[id] = $(id).value;
  return values;
}

export async function startFromForm(event) {
  if (event) event.preventDefault();
  if (app.busy) return;
  if (app.mode === 'room') return createRoom();
  if (app.mode === 'drill') {
    return startDrill({
      ...formValues(['difficulty', 'topic']),
      seconds: $('drillLength').value,
      targeted: $('drillTargeted').checked,
    });
  }
  app.busy = true;
  $('startBtn').disabled = true;
  $('startBtn').textContent = 'Preparing the table…';
  try {
    const config = {
      mode: app.mode,
      ...formValues(['difficulty', 'topic', 'bankroll', 'rounds', 'seconds', 'minutes', 'seed']),
    };
    if (app.mode === 'practice') config.log = answerLog();
    app.session = await api('/api/start', config);
    app.records = [];
    discardAnswers();
    const left = app.session.session_remaining;
    app.sessionEnd = left === null ? null : Date.now() + left * 1000;
    screen('play');
    renderRound();
  } catch (err) {
    toast(err.message);
  } finally {
    app.busy = false;
    $('startBtn').disabled = false;
    $('startBtn').textContent = START_LABEL[app.mode] || 'Start session ↗';
  }
}

// ---- Drawing a board

export function stats() {
  const { session, room } = app;
  $('roomCard').classList.toggle('hidden', !room);
  const ev =
    room && room.view && room.view.me ? room.view.me.ev : app.records.reduce((s, r) => s + r.expected_profit, 0);
  const pnl = session.bank - session.start_bank;
  $('bankStat').textContent = num(session.bank);
  $('pnlStat').textContent = signed(pnl);
  $('pnlStat').className = pnl < 0 ? 'negative' : 'positive';
  $('evStat').textContent = signed(ev);
  $('evStat').className = ev < 0 ? 'negative' : 'positive';
  $('sessionLabel').textContent = session.mode.toUpperCase() + ' / ' + session.difficulty.toUpperCase();
  $('seedPill').textContent = 'SEED ' + session.seed;
  const sprint = session.mode === 'sprint';
  $('fourthLabel').textContent = sprint ? 'Session clock' : 'Round';
  $('roundStat').textContent = sprint
    ? clock((app.sessionEnd - Date.now()) / 1000)
    : (session.round ? session.round.number : session.completed) + ' / ' + session.rounds;
  $('fourthSmall').textContent =
    room && room.view
      ? `Room ${room.view.code} · ${plural(room.view.players.length, 'player')}`
      : sprint
        ? plural(session.completed, 'round') + ' settled'
        : 'One shared outcome per board';
}

function eventCard(e, i) {
  const quick = [0, 1, 2, 5]
    .map(
      p =>
        `<button type="button" tabindex="-1" data-stake="${e.id}" data-pct="${p}">${p === 0 ? 'Pass' : p + '%'}</button>`,
    )
    .join('');
  return `<article class="event-card">
    <div class="event-head">
      <div><div class="event-number">PROPOSITION ${String(i + 1).padStart(2, '0')}</div><div class="event-title">${esc(e.label)}</div></div>
      <div class="quote">${num(e.odds)} : 1<small>PROFIT ODDS</small></div>
    </div>
    <div class="bet-fields">
      <div>
        <label for="estimate${e.id}">Your probability <span class="muted">(required · ±${app.session.tolerance} pts accepted)</span></label>
        <div class="input-with-unit"><input id="estimate${e.id}" class="est" type="text" placeholder="40 or 5/12" autocomplete="off" required></div>
        <div class="parsed tiny" id="parsed${e.id}"></div>
      </div>
      <div>
        <label for="stake${e.id}">Your stake</label>
        <div class="input-with-unit"><input id="stake${e.id}" class="stake" type="number" min="0" max="${app.session.bank}"
          step="0.01" inputmode="decimal" placeholder="0"><span>u</span></div>
        <div class="quick">${quick}</div>
      </div>
    </div>
    ${e.answer ? hintLadder(e) : ''}
  </article>`;
}

export function renderRound() {
  stats();
  const r = app.session.round;
  $('sessionTitle').textContent = 'Read the board.';
  $('roundView').classList.remove('hidden');
  $('reviewView').classList.add('hidden');
  $('roomWait').classList.add('hidden');
  $('validation').classList.add('hidden');
  $('clearBtn').disabled = false;
  $('settleBtn').textContent = app.room ? 'Lock in bets ↗' : 'Lock bets & reveal ↗';
  $('familyLabel').textContent = 'ROUND ' + String(r.number).padStart(2, '0') + ' / ' + r.topic.toUpperCase();
  $('boardTitle').textContent = r.title;
  $('boardRules').textContent = r.rules;
  $('boardGraphic').innerHTML = boardGraphic(r.kind, r.slots);
  $('focusNote').textContent = r.focus_note || '';
  $('focusNote').classList.toggle('hidden', !r.focus_note);
  $('events').innerHTML = r.events.map(eventCard).join('');
  document.querySelectorAll('.stake, .est').forEach(input => input.addEventListener('input', exposure));
  document.querySelectorAll('[data-stake]').forEach(button => {
    button.onclick = () => {
      $('stake' + button.dataset.stake).value = ((app.session.bank * Number(button.dataset.pct)) / 100).toFixed(2);
      exposure();
    };
  });
  wireHints(r.events);
  app.roundEnd = r.remaining === null ? null : Date.now() + r.remaining * 1000;
  exposure();
  startTimer();
  const first = $('estimate0');
  if (first && !app.room?.locked) first.focus({ preventScroll: true });
}

// ---- Reading bets

function getInputs() {
  const stakes = {};
  const estimates = {};
  const typed = {};
  for (const e of app.session.round.events) {
    stakes[e.id] = Number($('stake' + e.id).value || 0);
    const raw = $('estimate' + e.id).value.trim();
    const value = parseProb(raw);
    typed[e.id] = raw;
    estimates[e.id] = value === null ? '' : value;
  }
  return { stakes, estimates, typed };
}

/** Recompute committed money and whether the board can be locked, after every keystroke. */
export function exposure() {
  const { session, room } = app;
  const { stakes, estimates, typed } = getInputs();
  for (const e of session.round.events) {
    const hint = describeTyped(typed[e.id]);
    $('parsed' + e.id).textContent = hint.text;
    $('parsed' + e.id).className = 'parsed tiny ' + (hint.bad ? 'negative' : 'muted');
  }
  const answers = Object.values(estimates);
  const filled = answers.filter(v => v !== '').length;
  const missing = filled < answers.length;
  const total = Object.values(stakes).reduce((s, x) => s + x, 0);
  const invalid = Object.values(stakes).some(x => !Number.isFinite(x) || x < 0) || total > session.bank + 1e-8;
  $('committed').textContent = num(total);
  $('cash').textContent = num(session.bank - total);
  $('cash').className = 'mono ' + (invalid ? 'negative' : '');
  $('stakeMeter').style.width = Math.min(100, (100 * total) / session.bank) + '%';
  $('stakeMeter').style.background = total / session.bank > 0.3 ? '#a36b20' : 'var(--green)';
  $('settleBtn').disabled = invalid || missing || Boolean(room && room.locked);
  $('validation').textContent = invalid
    ? 'Use non-negative stakes whose total is at most your bankroll.'
    : `Enter a probability for every proposition to lock your bets, as a percentage or a fraction like 5/12 (${filled} of ${answers.length} entered).`;
  $('validation').classList.toggle('hidden', !(invalid || missing));
  $('exposureNote').textContent =
    total / session.bank > 0.3
      ? 'More than 30% committed. Check which bets can lose together.'
      : 'Unstaked money stays in your bankroll.';
}

export function clearStakes() {
  document.querySelectorAll('.stake').forEach(input => (input.value = ''));
  exposure();
}

// ---- Timers

export function startTimer() {
  clearInterval(app.timerHandle);
  tick();
  app.timerHandle = setInterval(tick, 200);
}

function tick() {
  if (!app.session || $('play').classList.contains('hidden')) return;
  const reviewing = !$('reviewView').classList.contains('hidden');
  if (app.sessionEnd !== null) {
    $('roundStat').textContent = clock((app.sessionEnd - Date.now()) / 1000);
    if (Date.now() >= app.sessionEnd && !app.busy) {
      if (reviewing) finish();
      else settle(true);
      return;
    }
  }
  if (reviewing) return;
  const remaining = app.roundEnd === null ? null : (app.roundEnd - Date.now()) / 1000;
  $('timer').textContent = remaining === null ? '∞' : clock(remaining);
  $('timer').classList.toggle('urgent', remaining !== null && remaining < 10);
  if (remaining !== null && remaining <= 0 && !app.busy) settle(true);
}

// ---- Settling, moving on, finishing

/** Lock the board. `auto` is the deadline firing: bad stakes become passes and blanks are allowed. */
export async function settle(auto) {
  if (app.busy || (app.room && app.room.locked)) return;
  const inputs = getInputs();
  const values = Object.values(inputs.stakes);
  if (auto) {
    if (values.some(x => !Number.isFinite(x) || x < 0) || values.reduce((a, b) => a + b, 0) > app.session.bank) {
      inputs.stakes = {};
      toast('Invalid stakes at the deadline: this board was passed.');
    }
  } else if (Object.values(inputs.estimates).some(v => v === '')) {
    toast('Enter a probability (0 to 100%, or a fraction like 5/12) for every proposition.');
    return;
  }
  app.busy = true;
  $('settleBtn').disabled = true;
  app.lastTyped = inputs.typed;
  try {
    if (app.room) {
      await submitRoom(inputs, auto);
      return;
    }
    const response = await api('/api/settle', {
      id: app.session.id,
      round: app.session.round.number,
      stakes: inputs.stakes,
      estimates: inputs.estimates,
      auto: auto === true,
    });
    app.session = response.session;
    app.records.push(response.result);
    holdAnswers(entriesFromRound(response.result, app.session, app.hints));
    renderReview(response.result, app.session.finished ? finish : nextRound);
    stats();
  } catch (err) {
    toast(err.message);
    app.roundEnd = null;
    app.sessionEnd = null;
    $('timer').textContent = 'Paused';
  } finally {
    app.busy = false;
    if (!$('roundView').classList.contains('hidden')) exposure();
  }
}

export async function nextRound() {
  if (app.room) return roomNext();
  if (app.busy) return;
  app.busy = true;
  try {
    app.session = await api('/api/next', { id: app.session.id });
    if (app.session.finished) {
      app.busy = false;
      return finish();
    }
    renderRound();
  } catch (err) {
    toast(err.message);
  } finally {
    app.busy = false;
  }
}

export function backToSetup() {
  app.session = null;
  app.room = null;
  screen('setup');
  refreshDashboard();
}

export async function finish() {
  if (app.busy || !app.session || app.room) return;
  app.busy = true;
  clearInterval(app.timerHandle);
  try {
    const summary = await api('/api/finish', { id: app.session.id });
    app.session.finished = true;
    if (summary.abandoned) {
      discardAnswers();
    } else {
      saveSummary(summary);
      commitAnswers();
    }
    renderSummary(summary, backToSetup);
    screen('summaryView');
  } catch (err) {
    toast(err.message);
    startTimer();
  } finally {
    app.busy = false;
  }
}

export function endSession() {
  if (app.room) {
    if (confirm('Leave this room? You will not be able to rejoin this game.')) leaveRoom();
  } else if (confirm('End this session? It will not count toward your dashboard or answer history.')) {
    finish();
  }
}

// ---- Dashboard shortcuts

export function refreshDashboard() {
  return renderDashboard(
    () => {
      setMode('practice');
      startFromForm();
    },
    () => {
      setMode('drill');
      $('drillTargeted').checked = true;
      startFromForm();
    },
  );
}

/** Keyboard: Enter locks a board, Space continues from a review, 1–4 jump to a stake box. */
export function onKey(e) {
  if ($('helpDialog').open || !app.session || $('play').classList.contains('hidden') || app.busy) return;
  const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName);
  const boardOpen = !$('roundView').classList.contains('hidden');
  if (e.key === 'Enter' && boardOpen) {
    e.preventDefault();
    if (!$('settleBtn').disabled) settle(false);
  } else if (!typing && e.code === 'Space' && !boardOpen) {
    e.preventDefault();
    if (app.session.finished) finish();
    else nextRound();
  } else if (!typing && /^[1-4]$/.test(e.key) && boardOpen) {
    const target = $('stake' + (Number(e.key) - 1));
    if (target) {
      e.preventDefault();
      target.focus();
      target.select();
    }
  }
}
