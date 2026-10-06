// Multiplayer rooms. The server owns the game; this page polls it once a second and redraws on change.

import { app } from './state.js';
import { commitAnswers, discardAnswers, entriesFromRound, holdAnswers, saveSummary } from './history.js';
import { renderRound, stats, backToSetup } from './play.js';
import { renderReview, renderSummary } from './review.js';
import {
  $,
  KIND_LABEL,
  RIGHT_CALL,
  WRONG_CALL,
  api,
  capitalise,
  esc,
  num,
  pct,
  plural,
  screen,
  signed,
  toast,
} from './util.js';

const STATUS = {
  locked: 'locked in ✓',
  thinking: 'thinking…',
  away: 'away',
  out: 'out of bankroll',
  left: 'left the game',
};

let pollHandle = null;
let polling = false;

function remember() {
  try {
    if (app.room) sessionStorage.setItem('edge-room', JSON.stringify({ code: app.room.code, secret: app.room.secret }));
    else sessionStorage.removeItem('edge-room');
  } catch (e) {
    /* storage unavailable: a refresh will simply leave the room */
  }
}

function playerName() {
  const name = $('playerName').value.trim();
  if (!name) {
    toast('Enter your name so your friends know who you are.');
    $('playerName').focus();
  }
  return name;
}

// ---- Joining and leaving

export async function createRoom() {
  const name = playerName();
  if (!name) return;
  app.busy = true;
  $('startBtn').disabled = true;
  try {
    const cfg = { name };
    for (const id of ['difficulty', 'topic', 'bankroll', 'rounds', 'seconds']) cfg[id] = $(id).value;
    enterRoom(await api('/api/room/create', cfg));
  } catch (err) {
    toast(err.message);
  } finally {
    app.busy = false;
    $('startBtn').disabled = false;
  }
}

export async function joinRoom() {
  const name = playerName();
  if (!name) return;
  const code = $('joinCode').value.trim().toUpperCase();
  if (!/^[A-Z]{4}$/.test(code)) {
    toast('Room codes are 4 letters.');
    $('joinCode').focus();
    return;
  }
  try {
    enterRoom(await api('/api/room/join', { code, name }));
  } catch (err) {
    toast(err.message);
  }
}

export function enterRoom(r) {
  app.room = { code: r.code, secret: r.secret, shown: null, locked: false, view: null };
  app.records = [];
  discardAnswers();
  remember();
  clearInterval(pollHandle);
  poll();
  pollHandle = setInterval(poll, 1000);
}

/** Pick a game back up after a page refresh. */
export function resumeRoom() {
  try {
    const saved = JSON.parse(sessionStorage.getItem('edge-room') || 'null');
    if (saved && saved.code && saved.secret) enterRoom(saved);
  } catch (e) {
    /* nothing to resume */
  }
}

export async function leaveRoom() {
  if (!app.room) return;
  try {
    await api('/api/room/leave', { code: app.room.code, secret: app.room.secret });
  } catch (e) {
    /* leaving anyway */
  }
  exitRoom();
}

function exitRoom() {
  clearInterval(pollHandle);
  clearInterval(app.timerHandle);
  discardAnswers();
  app.room = null;
  remember();
  $('roomCard').classList.add('hidden');
  backToSetup();
}

// ---- Talking to the server

async function poll() {
  if (!app.room || polling) return;
  polling = true;
  try {
    applyRoom(await api('/api/room/state', { code: app.room.code, secret: app.room.secret }));
  } catch (err) {
    if (/not in this room|No room/.test(err.message)) {
      toast(err.message);
      exitRoom();
    }
  } finally {
    polling = false;
  }
}

async function roomCall(action) {
  if (!app.room || app.busy) return;
  app.busy = true;
  try {
    applyRoom(await api('/api/room/' + action, { code: app.room.code, secret: app.room.secret }));
  } catch (err) {
    toast(err.message);
  } finally {
    app.busy = false;
  }
}

export function roomNext() {
  if (app.room && app.room.view && app.room.view.is_host) roomCall('next');
}

export async function submitRoom(inputs, auto) {
  try {
    const view = await api('/api/room/submit', {
      code: app.room.code,
      secret: app.room.secret,
      round: app.session.round.number,
      stakes: inputs.stakes,
      estimates: inputs.estimates,
      auto: auto === true,
    });
    lockBoard();
    applyRoom(view);
  } catch (err) {
    if (!auto) toast(err.message);
  }
}

// ---- Drawing

function lockBoard(message) {
  app.room.locked = true;
  document.querySelectorAll('#events input, #events button').forEach(el => (el.disabled = true));
  $('clearBtn').disabled = true;
  $('settleBtn').disabled = true;
  $('settleBtn').textContent = 'Locked in ✓';
  if (message) {
    $('roomWait').textContent = message;
    $('roomWait').classList.remove('hidden');
  }
}

function showWaiting(v) {
  const me = v.me || {};
  if (!me.in_play && !me.locked) return;
  const thinking = v.players.filter(p => p.status === 'thinking').map(p => p.name);
  const locked = v.players.filter(p => p.status === 'locked').length;
  const active = v.players.filter(p => p.status !== 'out' && p.status !== 'left').length;
  let text = '';
  if (app.room.locked)
    text = thinking.length ? 'Bets locked. Waiting for ' + thinking.join(', ') + '…' : 'Bets locked. Revealing…';
  else if (locked) text = `${locked} of ${active} players have locked in.`;
  $('roomWait').textContent = text;
  $('roomWait').classList.toggle('hidden', !text);
}

function nextButton() {
  const button = $('nextBtn');
  const v = app.room && app.room.view;
  if (!button || !v) return;
  button.disabled = !v.is_host;
  button.textContent = v.is_host
    ? v.last_round
      ? 'Final standings ↗'
      : 'Next round ↗'
    : 'Waiting for ' + v.host_name + '…';
}

function renderSitOut(v) {
  $('roundView').classList.add('hidden');
  $('reviewView').classList.remove('hidden');
  $('sessionTitle').textContent = 'Round ' + v.round + ' results.';
  $('reviewView').innerHTML = `<div class="result-hero"><div class="eyebrow">ROUND ${v.round} / THE REVEAL</div>
      <h3>You sat this round out.</h3>
      <p>Your bankroll has run out, so you are watching the rest of the game. The leaderboard shows how everyone did.</p></div>
    <div class="submit-bar"><span></span><button class="primary" id="nextBtn">Next round ↗</button></div>`;
  $('nextBtn').onclick = roomNext;
}

function renderStandings(v) {
  $('roomCardTitle').textContent = 'Room ' + v.code + ' · Leaderboard';
  const html = v.players
    .map((p, i) => {
      const note =
        v.state === 'playing'
          ? STATUS[p.status]
          : p.last !== null
            ? signed(p.last) + ' this round'
            : STATUS[p.status] || '';
      return `<div class="lb-row ${p.name === v.you ? 'me' : ''}"><span class="lb-rank">${i + 1}</span>
        <span class="lb-name">${esc(p.name)}${p.name === v.you ? ' (you)' : ''}<small>${note}</small></span>
        <span class="lb-bank mono">${num(p.bank)}<small class="${p.ev < 0 ? 'negative' : 'positive'}">EV ${signed(p.ev)}</small></span></div>`;
    })
    .join('');
  if ($('roomBoard').innerHTML !== html) $('roomBoard').innerHTML = html;
}

function renderLobby(v) {
  $('lobbyCode').textContent = v.code;
  const local = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  $('lobbyLink').value = location.origin + '/?room=' + v.code;
  $('linkNote').innerHTML = local
    ? `<span class="negative">This link only works on this computer.</span> Share the tunnel link or your Wi-Fi address from the
       terminal instead, with <span class="mono">/?room=${esc(v.code)}</span> on the end, or just tell friends the code.`
    : '';
  $('lobbyInfo').textContent = [
    capitalise(v.difficulty),
    v.topic === 'mixed' ? 'mixed table' : v.topic + ' only',
    plural(v.rounds, 'round'),
    v.seconds ? num(v.seconds) + ' s per round' : 'no time limit',
    num(v.start_bank) + ' units each',
  ].join(' · ');
  $('lobbyCount').textContent = `(${v.players.length} / 12)`;
  const players = v.players
    .map(
      p => `<div class="lobby-player"><span class="avatar">${esc(p.name.slice(0, 1).toUpperCase())}</span>${esc(p.name)}
      ${p.name === v.you ? ' <span class="tiny muted">(you)</span>' : ''}${p.host ? ' <span class="badge">HOST</span>' : ''}
      ${p.status === 'away' ? ' <span class="tiny muted">away</span>' : ''}</div>`,
    )
    .join('');
  if ($('lobbyPlayers').innerHTML !== players) $('lobbyPlayers').innerHTML = players;
  const action = v.is_host
    ? `<button class="primary" id="roomStart">Start game ↗</button><p class="tiny muted">${
        v.players.length < 2
          ? 'Waiting for friends to join. You can also start on your own.'
          : 'Everyone gets the same boards. Start when your friends are in.'
      }</p>`
    : `<p class="muted">Waiting for ${esc(v.host_name)} to start the game…</p>`;
  if ($('lobbyAction').dataset.html !== action) {
    $('lobbyAction').dataset.html = action;
    $('lobbyAction').innerHTML = action;
    if ($('roomStart')) $('roomStart').onclick = () => roomCall('start');
  }
}

/** Everyone's bets on the board that just closed, side by side. */
function comparison(c) {
  if (!c || !c.players.length) return '';
  const rows = c.players;
  const head = c.events
    .map((e, i) => {
      const right = rows.filter(r => RIGHT_CALL.has(r.bets[i].kind)).length;
      const buy = e.ev > 1e-9;
      return `<th class="cmp-head"><div class="cmp-label">${esc(e.label)}</div><div class="mono">${num(e.odds)} : 1</div>
        <div class="cmp-truth">True ${pct(e.p)} · needs ${pct(e.breakeven)}</div>
        <span class="badge ${buy ? '' : 'bad'}">${buy ? 'BUY' : 'PASS'} · EV ${signed(e.ev)}</span>
        <div class="cmp-truth">Right call: ${right} / ${rows.length}</div></th>`;
    })
    .join('');
  const body = rows
    .map((r, index) => {
      const cells = r.bets
        .map(b => {
          const verdict = b.kind === 'good_pass' ? 'Right pass' : KIND_LABEL[b.kind] || '';
          const cls = RIGHT_CALL.has(b.kind) ? 'right' : WRONG_CALL.has(b.kind) ? 'wrong' : '';
          return `<td class="cmp-cell ${cls}"><strong class="mono">${b.stake > 0 ? num(b.stake) + ' u' : 'Pass'}</strong>
            <span>${b.estimate === null ? 'no estimate' : num(b.estimate, 1) + '% ' + (b.within ? '✓' : '✗')}</span>
            <small>${esc(verdict)}${b.stake > 0 ? ' · ' + signed(b.profit) : ''}</small></td>`;
        })
        .join('');
      const best =
        index === 0 && rows.length > 1 && r.expected > 0 ? '<small class="positive">Best decisions</small>' : '';
      return `<tr class="${r.you ? 'me' : ''}">
        <td class="cmp-name">${esc(r.name)}${r.you ? ' (you)' : ''}${best}${r.timed_out ? '<small class="negative">Timed out</small>' : ''}</td>
        ${cells}
        <td class="mono cmp-total"><span class="${r.expected < 0 ? 'negative' : 'positive'}">EV ${signed(r.expected)}</span>
          <span>P&amp;L ${signed(r.profit)}</span><small>${r.in_range} / ${c.events.length} estimates in range</small></td></tr>`;
    })
    .join('');
  return `<section class="summary-panel compare">
    <div class="eyebrow" style="color:var(--green)">HOW EVERYONE PLAYED</div>
    <h3>Compare your bets with your friends</h3>
    <p class="tiny muted">Green means the right call for that price (buy a positive-EV quote, pass a negative one); red means an overpriced
      buy or a missed edge. ✓ or ✗ marks whether an estimate was within ±${app.session.tolerance} points. Players are sorted by
      expected profit, which rewards decisions rather than luck.</p>
    <div class="review-table"><table class="cmp"><thead><tr><th>Player</th>${head}<th>This round</th></tr></thead>
      <tbody>${body}</tbody></table></div>
  </section>`;
}

function finalStandings(v) {
  const top = v.players[0];
  const rows = v.players
    .map(
      (
        p,
        i,
      ) => `<tr class="${p.name === v.you ? 'me' : ''}"><td>${i + 1}</td><td>${esc(p.name)}</td><td class="mono">${num(p.bank)}</td>
      <td class="mono ${p.profit < 0 ? 'negative' : 'positive'}">${signed(p.profit)}</td>
      <td class="mono ${p.ev < 0 ? 'negative' : 'positive'}">${signed(p.ev)}</td><td class="mono">${p.in_range} / ${p.estimates}</td></tr>`,
    )
    .join('');
  return `<div class="summary-panel">
    <div class="eyebrow muted">ROOM ${esc(v.code)} / FINAL STANDINGS</div>
    <h2 style="margin:8px 0 16px">${top.name === v.you ? 'You win!' : esc(top.name) + ' wins.'}</h2>
    <div class="review-table"><table>
      <thead><tr><th>#</th><th>Player</th><th>Bankroll</th><th>P&amp;L</th><th>Expected profit</th><th>Estimates in range</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="tiny muted" style="margin:12px 0 0">Bankroll decides the winner, but luck plays a part. Expected profit shows who made the best decisions.</p>
  </div>`;
}

/** Bring the screen in line with the latest room state. */
function applyRoom(v) {
  const room = app.room;
  if (!room) return;
  room.view = v;
  if (v.state === 'lobby') {
    renderLobby(v);
    if (room.shown !== 'lobby') {
      room.shown = 'lobby';
      screen('lobby');
    }
    return;
  }
  const me = v.me || {};
  // The play screen reads app.session, so describe the room in the same shape.
  app.session = {
    id: me.session_id,
    mode: 'room',
    difficulty: v.difficulty,
    seed: 'ROOM ' + v.code,
    bank: me.bank,
    start_bank: v.start_bank,
    rounds: v.rounds,
    completed: me.completed,
    tolerance: v.tolerance,
    finished: v.state === 'finished',
    round: v.board || null,
  };
  renderStandings(v);

  if (v.state === 'playing') {
    const key = 'play' + v.round;
    if (room.shown !== key) {
      room.shown = key;
      room.locked = false;
      screen('play');
      renderRound();
      if (me.locked) lockBoard();
      else if (!me.in_play)
        lockBoard('Your bankroll has run out, so you are watching this game. The leaderboard updates live.');
    }
    showWaiting(v);
  } else if (v.state === 'reveal') {
    const key = 'reveal' + v.round;
    if (room.shown !== key) {
      room.shown = key;
      room.locked = false;
      clearInterval(app.timerHandle);
      screen('play');
      if (v.result) {
        app.records.push(v.result);
        holdAnswers(entriesFromRound(v.result, app.session));
        renderReview(v.result, roomNext);
      } else {
        renderSitOut(v);
      }
      const html = comparison(v.comparison);
      const anchor = $('reviewView').querySelector('.debrief') || $('reviewView').querySelector('.submit-bar');
      if (html && anchor) anchor.insertAdjacentHTML('beforebegin', html);
    }
    nextButton();
  } else if (v.state === 'finished' && room.shown !== 'done') {
    room.shown = 'done';
    clearInterval(pollHandle);
    clearInterval(app.timerHandle);
    if (v.summary) {
      saveSummary(v.summary);
      commitAnswers();
      renderSummary(v.summary, backToSetup);
    } else {
      $('summaryView').innerHTML = '';
    }
    const head = $('summaryView').firstElementChild;
    if (head) head.insertAdjacentHTML('afterend', finalStandings(v));
    else $('summaryView').innerHTML = finalStandings(v);
    screen('summaryView');
    app.room = null;
    remember();
    return;
  }
  stats();
}

export async function copyInvite() {
  try {
    await navigator.clipboard.writeText($('lobbyLink').value);
    toast('Link copied.');
  } catch (e) {
    $('lobbyLink').select();
    toast('Press Ctrl+C / Cmd+C to copy.');
  }
}
