// Small helpers shared by every screen: DOM access, formatting, the API client and safe storage.

export const $ = id => document.getElementById(id);

const TOKEN = document.querySelector('meta[name="edge-token"]').content;

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = s => String(s).replace(/[&<>"']/g, c => ESCAPES[c]);

export const num = (n, digits = 2) =>
  Number(n).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: digits });
export const signed = n => (n > 0 ? '+' : '') + num(n);
export const pct = p => num(p * 100, 2) + '%';
export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
export const capitalise = s => s.charAt(0).toUpperCase() + s.slice(1);

export function clock(seconds) {
  const s = Math.max(0, Math.ceil(seconds));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

// One place for the verdict names the server uses (see coaching.coach_round).
export const KIND_LABEL = {
  hedge: 'Hedge leg',
  bad_buy: 'Overpriced',
  good_buy: 'Good buy',
  missed_edge: 'Missed edge',
  covered_pass: 'Covered',
  good_pass: 'Pass',
  fair_bet: 'No edge',
};
export const RIGHT_CALL = new Set(['good_buy', 'good_pass', 'covered_pass', 'hedge']);
export const WRONG_CALL = new Set(['bad_buy', 'missed_edge']);

let toastTimer = null;
export function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 4500);
}

async function post(path, data) {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Edge-Token': TOKEN },
    body: JSON.stringify(data),
  });
}

export async function api(path, data) {
  const response = await post(path, data);
  let body;
  try {
    body = await response.json();
  } catch (e) {
    throw Error('Unexpected response. Check the Python window.');
  }
  if (!response.ok) throw Error(body.error || 'Request failed.');
  return body;
}

export async function download(path, data, filename) {
  const response = await post(path, data);
  if (!response.ok) throw Error('Could not export this session.');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Read a probability typed as a percentage ("41.67", "41.67%") or a fraction ("5/12"). */
export function parseProb(text) {
  const t = String(text).trim().replace(/\s*%$/, '');
  if (!t) return null;
  const fraction = t.match(/^(\d*\.?\d+)\s*\/\s*(\d*\.?\d+)$/);
  let value;
  if (fraction) {
    if (Number(fraction[2]) === 0) return null;
    value = (100 * Number(fraction[1])) / Number(fraction[2]);
  } else if (/^\d*\.?\d+$/.test(t)) {
    value = Number(t);
  } else {
    return null;
  }
  return value >= 0 && value <= 100 ? value : null;
}

/** Explain how a typed probability was read, for the hint under an input. */
export function describeTyped(raw) {
  const value = parseProb(raw);
  if (raw.trim() && value === null)
    return { bad: true, text: 'Not understood. Use 0 to 100, or a fraction like 5/12.' };
  return { bad: false, text: raw.includes('/') && value !== null ? '= ' + num(value, 2) + '%' : '' };
}

// Browser storage can be missing or full (private windows, blocked cookies), so never let it throw.
export const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      return false;
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      /* nothing to clear */
    }
  },
};

/** Show exactly one of the main screens. */
export function screen(which) {
  for (const id of ['setup', 'play', 'drill', 'lobby', 'summaryView']) $(id).classList.toggle('hidden', id !== which);
  window.scrollTo({ top: 0, behavior: 'instant' });
}

const TOKEN_CLASS = {
  cards: 'card',
  dice: 'die',
  coins: 'coin',
  urn: 'marble',
  letters: 'env',
  people: 'person',
  number: 'tile',
};

/** Face-down cards, blank dice and so on: a picture of the board before the reveal. */
export function boardGraphic(kind, slots) {
  const cls = TOKEN_CLASS[kind] || 'die';
  const n = slots.length;
  const step = kind === 'cards' ? 8 : n > 4 ? 2 : 4;
  const items = slots.map((slot, i) => {
    const tilt = ((i - (n - 1) / 2) * step).toFixed(1);
    return `<span class="gfx-${cls}" style="--r:${tilt}deg">${kind === 'cards' ? '' : esc(slot)}</span>`;
  });
  return items.join('') + '<span class="gfx-note">Hidden until you answer</span>';
}
