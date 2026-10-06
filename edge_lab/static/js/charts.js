// SVG charts. Each function returns markup; attachTooltips wires hover for charts that need it.

import { esc, num, pct, signed } from './util.js';

const INK_MUTED = '#627067';
const GRID = '#e3e7de';
const AXIS = '#cbd4c2';
const GREEN = '#266344';
const RED = '#a73837';
const AMBER = '#8a5c12';

/** Exact distribution of one quantity on the board, with the realised value highlighted. */
export function histogram(data, actual, label) {
  const w = 560;
  const h = 105;
  const max = Math.max(...data.map(d => d.probability));
  const step = w / data.length;
  const bars = data.map((d, i) => {
    const bh = (d.probability / max) * 85;
    const fill = d.value === actual ? '#91b747' : '#cedac1';
    return `<rect x="${i * step + 1}" y="${90 - bh}" width="${Math.max(1, step - 2)}" height="${bh}" rx="2" fill="${fill}">
      <title>${d.value}: ${pct(d.probability)}</title></rect>`;
  });
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img"
      aria-label="Exact distribution of ${esc(label)}; realised value highlighted">
    ${bars.join('')}
    <text x="0" y="104" font-size="10" fill="${INK_MUTED}">${data[0].value}</text>
    <text x="${w / 2}" y="104" text-anchor="middle" font-size="10" fill="${INK_MUTED}">${esc(label)}</text>
    <text x="${w}" y="104" text-anchor="end" font-size="10" fill="${INK_MUTED}">${data[data.length - 1].value}</text>
  </svg>`;
}

/** Bankroll after each round of a session. */
export function lineChart(path) {
  const w = 600;
  const h = 160;
  const pad = 12;
  const min = Math.min(...path);
  const range = Math.max(Math.max(...path) - min, 1);
  const point = (v, i) => [
    pad + (i / Math.max(1, path.length - 1)) * (w - 2 * pad),
    h - pad - ((v - min) / range) * (h - 2 * pad),
  ];
  const y0 = point(path[0], 0)[1];
  const dots = path.map((v, i) => {
    const [x, y] = point(v, i);
    return `<circle cx="${x}" cy="${y}" r="3" fill="${GREEN}"><title>After round ${i}: ${num(v)}</title></circle>`;
  });
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Bankroll by completed round">
    <line x1="${pad}" x2="${w - pad}" y1="${y0}" y2="${y0}" stroke="${AXIS}" stroke-dasharray="4 5"/>
    <polyline points="${path.map((v, i) => point(v, i).join(',')).join(' ')}" fill="none" stroke="${GREEN}"
      stroke-width="2.5" stroke-linejoin="round"/>
    ${dots.join('')}
  </svg>`;
}

/** Profit per round as bars, with cumulative realised and expected profit as lines. */
export function pnlChart(items) {
  const n = items.length;
  if (!n) return '';
  const w = 960;
  const pad = 14;
  const top = 10;
  const h1 = 120;
  const gap = 22;
  const h2 = 64;
  const height = top + h1 + gap + h2 + 16;
  const bw = (w - 2 * pad) / n;
  let realised = 0;
  let expected = 0;
  const cum = items.map(x => (realised += x.pnl));
  const cev = items.map(x => (expected += x.ev));
  const all = [0, ...cum, ...cev];
  const min = Math.min(...all);
  const range = Math.max(Math.max(...all) - min, 1);
  const X = i => pad + (i + 0.5) * bw;
  const Y = v => top + h1 - ((v - min) / range) * h1;
  const line = values => values.map((v, i) => X(i).toFixed(1) + ',' + Y(v).toFixed(1)).join(' ');
  const maxAbs = Math.max(...items.map(x => Math.abs(x.pnl)), 1);
  const base = top + h1 + gap + h2 / 2;
  const inset = Math.min(1, bw * 0.15);

  const sessionBreaks = items
    .map((x, i) =>
      x.start && i > 0
        ? `<line x1="${pad + i * bw}" x2="${pad + i * bw}" y1="${top}" y2="${height - 16}" stroke="#d9ded4"/>`
        : '',
    )
    .join('');
  const dots =
    n <= 40
      ? cum
          .map(
            (v, i) =>
              `<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${GREEN}"><title>${esc(items[i].label)}: cumulative P&amp;L ${signed(v)}</title></circle>`,
          )
          .join('')
      : '';
  const bars = items.map((x, i) => {
    const hh = Math.max(0.5, ((Math.abs(x.pnl) / maxAbs) * h2) / 2);
    return `<rect x="${pad + i * bw + inset}" y="${x.pnl >= 0 ? base - hh : base}" width="${Math.max(1, bw - 2 * inset)}"
      height="${hh}" rx="1" fill="${x.pnl >= 0 ? GREEN : RED}">
      <title>${esc(x.label)}: ${signed(x.pnl)} realised, ${signed(x.ev)} expected</title></rect>`;
  });
  return `<svg class="chart" viewBox="0 0 ${w} ${height}" role="img"
      aria-label="Realised profit and loss per round with cumulative realised and expected profit">
    <line x1="${pad}" x2="${w - pad}" y1="${Y(0)}" y2="${Y(0)}" stroke="${AXIS}" stroke-dasharray="4 5"/>
    ${sessionBreaks}
    <polyline points="${line(cev)}" fill="none" stroke="${AMBER}" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>
    <polyline points="${line(cum)}" fill="none" stroke="${GREEN}" stroke-width="2.5" stroke-linejoin="round"/>
    ${dots}
    <line x1="${pad}" x2="${w - pad}" y1="${base}" y2="${base}" stroke="${AXIS}"/>
    ${bars.join('')}
    <text x="${pad}" y="${height - 2}" font-size="10" fill="${INK_MUTED}">Oldest round</text>
    <text x="${w - pad}" y="${height - 2}" text-anchor="end" font-size="10" fill="${INK_MUTED}">Latest round</text>
  </svg>
  <div class="legend">
    <span><i></i>Cumulative realised P&amp;L (${signed(realised)})</span>
    <span><i class="dash"></i>Cumulative expected profit (${signed(expected)})</span>
    <span><i class="bar"></i>Profit or loss per round</span>
  </div>`;
}

// Calibration colours were checked with the dataviz palette validator against the page surface.
const CAL_AVG = '#2a7a4b';
const CAL_POINT = '#c08a2a';

/**
 * Your estimate against the true probability. Dots on the dashed diagonal are perfectly calibrated;
 * the line shows your average estimate in each 10-point band of true probability.
 */
export function calibrationChart(profile) {
  const size = 320;
  const pad = { left: 40, right: 12, top: 12, bottom: 34 };
  const inner = size - pad.left - pad.right;
  const X = v => pad.left + (v / 100) * inner;
  const Y = v => pad.top + inner - (v / 100) * inner;
  const ticks = [0, 25, 50, 75, 100];
  const grid = ticks
    .map(
      t => `<line x1="${X(0)}" x2="${X(100)}" y1="${Y(t)}" y2="${Y(t)}" stroke="${GRID}"/>
      <line x1="${X(t)}" x2="${X(t)}" y1="${Y(0)}" y2="${Y(100)}" stroke="${GRID}"/>
      <text x="${X(0) - 6}" y="${Y(t) + 3.5}" text-anchor="end" font-size="10" fill="${INK_MUTED}">${t}%</text>
      <text x="${X(t)}" y="${Y(0) + 14}" text-anchor="middle" font-size="10" fill="${INK_MUTED}">${t}%</text>`,
    )
    .join('');
  const points = profile.points
    .map(
      ([t, e]) =>
        `<circle cx="${X(t).toFixed(1)}" cy="${Y(e).toFixed(1)}" r="2.5" fill="${CAL_POINT}" fill-opacity="0.45"/>`,
    )
    .join('');
  const bins = profile.calibration;
  const path = bins.map(b => `${X(b.true).toFixed(1)},${Y(b.est).toFixed(1)}`).join(' ');
  const binDots = bins
    .map(b => {
      const tip = `True ${b.lo}–${b.hi}%: you said ${num(b.est, 1)}% on average (truth ${num(b.true, 1)}%) · ${b.n} answer${b.n === 1 ? '' : 's'}`;
      return `<g class="cal-dot" data-tip="${esc(tip)}" tabindex="0" role="img" aria-label="${esc(tip)}">
        <circle class="cal-hit" cx="${X(b.true)}" cy="${Y(b.est)}" r="12"/>
        <circle cx="${X(b.true)}" cy="${Y(b.est)}" r="5" fill="${CAL_AVG}" stroke="#fffef9" stroke-width="2"/>
      </g>`;
    })
    .join('');
  return `<div class="cal-wrap">
    <svg class="chart" viewBox="0 0 ${size} ${size}" role="img"
        aria-label="Your probability estimates against the true probability, with a diagonal for perfect calibration">
      ${grid}
      <line x1="${X(0)}" y1="${Y(0)}" x2="${X(100)}" y2="${Y(100)}" stroke="#9aa39c" stroke-width="1.5" stroke-dasharray="5 4"/>
      <text x="${X(88)}" y="${Y(94)}" text-anchor="end" font-size="10" fill="${INK_MUTED}">perfect</text>
      ${points}
      ${bins.length > 1 ? `<polyline points="${path}" fill="none" stroke="${CAL_AVG}" stroke-width="2" stroke-linejoin="round"/>` : ''}
      ${binDots}
      <text x="${X(50)}" y="${size - 4}" text-anchor="middle" font-size="10" fill="${INK_MUTED}">True probability</text>
      <text transform="translate(10 ${Y(50)}) rotate(-90)" text-anchor="middle" font-size="10" fill="${INK_MUTED}">Your estimate</text>
    </svg>
    <div class="cal-tip hidden" role="tooltip"></div>
  </div>
  <div class="legend">
    <span><i class="line-a"></i>Your average estimate per band</span>
    <span><i class="dot-a"></i>Each answer</span>
    <span><i class="ref"></i>Perfect calibration</span>
  </div>`;
}

/** Table view of the calibration bins, for exact numbers and screen readers. */
export function calibrationTable(profile) {
  const rows = profile.calibration
    .map(
      b => `<tr><td>${b.lo}–${b.hi}%</td><td class="mono">${num(b.true, 1)}%</td><td class="mono">${num(b.est, 1)}%</td>
      <td class="mono ${Math.abs(b.est - b.true) >= 5 ? 'negative' : ''}">${signed(Number((b.est - b.true).toFixed(1)))}</td><td class="mono">${b.n}</td></tr>`,
    )
    .join('');
  return `<div class="review-table"><table><thead><tr><th>True range</th><th>Avg truth</th><th>Your avg</th><th>Bias (pts)</th><th>Answers</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

/** Hover and focus tooltips for chart marks that carry data-tip. */
export function attachTooltips(container) {
  container.querySelectorAll('.cal-wrap').forEach(wrap => {
    const tip = wrap.querySelector('.cal-tip');
    const show = target => {
      const box = wrap.getBoundingClientRect();
      const dot = target.getBoundingClientRect();
      tip.textContent = target.dataset.tip;
      tip.style.left = dot.left + dot.width / 2 - box.left + 'px';
      tip.style.top = dot.top - box.top + 'px';
      tip.classList.remove('hidden');
    };
    const hide = () => tip.classList.add('hidden');
    wrap.querySelectorAll('[data-tip]').forEach(el => {
      el.addEventListener('mouseenter', () => show(el));
      el.addEventListener('focus', () => show(el));
      el.addEventListener('mouseleave', hide);
      el.addEventListener('blur', hide);
    });
  });
}
