// Mutable state shared between modules. Kept in one object so every module sees the same values.

export const app = {
  mode: 'coach', // the selected mode card on the setup screen
  session: null, // the current betting session as last reported by the server (or built from a room)
  records: [], // settled rounds of the current session, newest last
  busy: false, // a request is in flight; blocks double submissions
  roundEnd: null, // wall-clock ms when the current round's timer runs out (null: untimed)
  sessionEnd: null, // wall-clock ms when a sprint ends
  timerHandle: null,
  lastTyped: {}, // what the player typed per proposition, to echo fractions back in the review
  hints: {}, // coach hints opened per proposition id on the current board (0 to 3)
  pending: [], // answers from the current session, added to the history log once it completes
  room: null, // multiplayer room state (see rooms.js)
  drill: null, // pricing drill state (see drill.js)
};
