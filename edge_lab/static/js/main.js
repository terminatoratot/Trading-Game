// Entry point: wire the page's controls to the modules, then show the dashboard.

import { app } from './state.js';
import { answerDrill, finishDrill, showTyped } from './drill.js';
import {
  clearStakes,
  endSession,
  onKey,
  refreshDashboard,
  setMode,
  settle,
  showPracticeNote,
  startFromForm,
} from './play.js';
import { copyInvite, joinRoom, leaveRoom, resumeRoom } from './rooms.js';
import { $ } from './util.js';

document.querySelectorAll('[data-mode]').forEach(button => (button.onclick = () => setMode(button.dataset.mode)));
$('configForm').onsubmit = startFromForm;
$('drillTargeted').onchange = showPracticeNote;
$('helpBtn').onclick = () => $('helpDialog').showModal();
$('closeHelp').onclick = () => $('helpDialog').close();

// Betting board
$('settleBtn').onclick = () => settle(false);
$('clearBtn').onclick = clearStakes;
$('endBtn').onclick = endSession;
document.addEventListener('keydown', onKey);

// Pricing drill
$('drillForm').onsubmit = answerDrill;
$('drillInput').addEventListener('input', showTyped);
$('drillEnd').onclick = () => {
  if (confirm('End this drill? It will not count toward your dashboard or answer history.')) finishDrill(false);
};

// Multiplayer
$('joinBtn').onclick = joinRoom;
$('joinCode').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    e.preventDefault();
    joinRoom();
  }
});
$('leaveBtn').onclick = () => confirm('Leave this room?') && leaveRoom();
$('copyLink').onclick = copyInvite;

window.addEventListener('beforeunload', e => {
  const inProgress = (app.session && !app.session.finished) || (app.drill && !app.drill.finished);
  if (inProgress) {
    e.preventDefault();
    e.returnValue = '';
  }
});

document.addEventListener('profile-updated', showPracticeNote);

// An invite link (?room=CODE) opens the multiplayer card with the code filled in.
const invited = new URLSearchParams(location.search).get('room');
setMode(invited ? 'room' : 'coach');
if (invited) {
  $('joinCode').value = invited.toUpperCase().slice(0, 4);
  setTimeout(() => $('playerName').focus(), 50);
}
refreshDashboard();
resumeRoom();
