"""Decision feedback: joint Kelly sizing, per-round debriefs and session training plans."""

import collections
import math

from .probability import FAMILIES, wins

CLEAR_EDGE = 1.10  # a "clear buy" pays 10% more profit odds than the fair price
DRILLS = {
    'dice': 'Write out the 6×6 grid (or one grid per value of the third die) and count cells rather than guessing.',
    'cards': 'Cards are drawn WITHOUT replacement: count hands with C(52, n), and use complements ("at least one" = 1 − none).',
    'coins': 'Use binomial counts C(n, k) over the 2^n equally likely sequences, and recursions (Fibonacci-style) for runs and patterns.',
    'puzzles': 'Look for symmetry first (every position or person is alike), then complements; when the space is small, list it.',
}


def win_patterns(events, rows):
    """Group the shared sample space by which events win: [(win pattern, probability)]."""
    counts = collections.Counter(tuple(wins(e, row) for e in events) for row in rows)
    return [(pattern, n / len(rows)) for pattern, n in counts.items()]


def payoff_table(events, patterns):
    return [([e['odds'] if w else -1 for e, w in zip(events, pattern)], prob) for pattern, prob in patterns]


def log_growth(table, fractions):
    """Expected log wealth of staking these bankroll fractions; -inf if the bankroll can be wiped out."""
    total = 0.0
    for returns, prob in table:
        wealth = 1 + sum(f * r for f, r in zip(fractions, returns))
        if wealth <= 1e-12:
            return -math.inf
        total += prob * math.log(wealth)
    return total


def joint_kelly(table, n):
    """Bankroll fractions maximising expected log wealth when all events settle on ONE outcome.

    Growth is concave in the fractions, so coordinate ascent with a golden-section
    search on each fraction converges to the joint optimum.
    """
    f = [0.0] * n
    for _ in range(30):
        before = list(f)
        for i in range(n):

            def at(x):
                return log_growth(table, f[:i] + [x] + f[i + 1 :])

            lo, hi = 0.0, 1 - (sum(f) - f[i])
            for _ in range(32):
                a, b = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
                if at(a) < at(b):
                    lo = a
                else:
                    hi = b
            mid = (lo + hi) / 2
            f[i] = mid if at(mid) > at(0.0) else 0.0
        if max(abs(x - y) for x, y in zip(f, before)) < 1e-7:
            break
    return [x if x > 1e-6 else 0.0 for x in f]


def plan_stats(events, patterns, stakes):
    """Exact profit statistics of a stake plan under the shared outcome."""
    pnls = [
        (sum(s * (e['odds'] if w else -1) for e, s, w in zip(events, stakes, pattern)), prob)
        for pattern, prob in patterns
    ]
    return {
        'expected': sum(x * p for x, p in pnls),
        'worst': min(x for x, _ in pnls),
        'loss_probability': sum(p for x, p in pnls if x < -1e-8),
    }


def coach_round(events, result, bank, timed_out, patterns, tolerance):
    """Say what a better play on this board looked like: which prices to buy, how much, and why.

    Annotates each entry of `result` with a 'coach' dict and returns the board-level debrief.
    """
    table = payoff_table(events, patterns)
    kelly = joint_kelly(table, len(events))
    suggested = [round(bank * f / 2, 2) for f in kelly]  # half-Kelly on the joint distribution
    plan = plan_stats(events, patterns, suggested)
    fractions = [x['stake'] / bank for x in result]
    growth = log_growth(table, fractions)
    edges = [x for x in result if x['ev'] > 1e-9]
    best = max(edges, key=lambda x: x['ev']) if edges else None
    staked = sum(x['stake'] for x in result)
    mistakes, others, flags = [], [], []

    def lesson(bucket, tone, title, body):
        bucket.append({'tone': tone, 'title': title, 'body': body})

    for x, rec in zip(result, suggested):
        p, be = 100 * x['p'], 100 * x['breakeven']
        clear = round(x['fair_odds'] * CLEAR_EDGE, 2)
        tip = x['explanation']['tip']
        if x['stake'] > 0 and x['ev'] < -1e-9 and rec > 0:
            # Overlapping propositions can make a losing price worth holding as a hedge leg.
            kind = 'hedge'
            verdict = (
                'Hedge leg: negative EV on its own, but the best joint plan holds about %.2f of it to offset the other bets.'
                % rec
            )
        elif x['stake'] > 0 and x['ev'] < -1e-9:
            kind = 'bad_buy'
            verdict = 'Overpriced: you needed more than %.2f%%, the true chance is %.2f%%.' % (be, p)
            alternative = (
                'The best buy here was “%s” at %.2f : 1 (EV %+.3f per unit).'
                % (best['label'], best['odds'], best['ev'])
                if best
                else 'Nothing on this board beat its break-even, so the best play was to pass.'
            )
            lesson(
                mistakes,
                'bad',
                'Bad buy: ' + x['label'],
                'You staked %.2f at %.2f : 1. The true probability is %.2f%% but break-even is %.2f%%, so each unit staked lost %.3f on average. '
                'This price only becomes fair at %.2f : 1 and a clear buy from about %.2f : 1. %s '
                'Strategy: work out break-even = 1/(1+b) first and stake only when your probability clears it. How to get the probability: %s'
                % (x['stake'], x['odds'], p, be, -x['ev'], x['fair_odds'], clear, alternative, tip),
            )
        elif x['stake'] > 0 and x['ev'] > 1e-9:
            kind = 'good_buy'
            ratio = x['stake'] / rec if rec else None
            size = (
                'Size: about %.1f× the suggested stake.' % ratio
                if ratio and (ratio > 2 or ratio < 0.5)
                else 'Size is in a sensible range.'
            )
            verdict = 'Good buy: the price beats break-even by %.2f points. %s' % (p - be, size)
        elif x['ev'] > 1e-9:
            if rec > 0:
                kind = 'missed_edge'
                verdict = 'Missed edge: EV %+.3f per unit. Suggested stake about %.2f.' % (x['ev'], rec)
                lesson(
                    mistakes,
                    'bad',
                    'Missed edge: ' + x['label'],
                    'At %.2f : 1 you needed %.2f%% and the true probability is %.2f%% (EV %+.3f per unit). '
                    'A half-Kelly plan for the whole board stakes about %.2f units here. '
                    'Strategy: rank the quotes by (probability − break-even) and put a small stake on the biggest gap instead of passing. If you could not price it, practise: %s'
                    % (x['odds'], be, p, x['ev'], rec, tip),
                )
            else:
                kind = 'covered_pass'
                verdict = (
                    'Reasonable pass: positive EV, but a better bet on this board covers the same outcome.'
                )
        else:
            kind = 'good_pass' if x['stake'] == 0 else 'fair_bet'
            verdict = (
                'Good pass: this price is worse than fair (fair is %.2f : 1).' % x['fair_odds']
                if x['stake'] == 0
                else 'Zero-EV bet: no edge to earn.'
            )
        estimate = None
        if x['estimate'] is not None:
            err = x['estimate'] - p
            says_buy = x['estimate'] / 100 > x['breakeven']
            flipped = says_buy != (x['ev'] > 1e-9) and abs(err) >= 3
            estimate = {'signed_error': err, 'flipped': flipped}
            if flipped:
                flags.append('estimate_flip')
                lesson(
                    mistakes,
                    'bad',
                    'Your estimate flipped the call: ' + x['label'],
                    'You estimated %.2f%%, %s the %.2f%% break-even, so your numbers said to %s. The true probability is %.2f%% (you were %.2f points %s), so the right call was to %s. '
                    '%s %s'
                    % (
                        x['estimate'],
                        'above' if says_buy else 'below',
                        be,
                        'buy' if says_buy else 'pass',
                        p,
                        abs(err),
                        'too high' if err > 0 else 'too low',
                        'buy' if x['ev'] > 1e-9 else 'pass',
                        x['explanation']['counting'],
                        tip,
                    ),
                )
            elif abs(err) > tolerance:
                lesson(
                    others,
                    'tip',
                    'Estimate %.1f points %s, outside ±%d: %s'
                    % (abs(err), 'high' if err > 0 else 'low', tolerance, x['label']),
                    'You said %.2f%%, the true probability is %.2f%%. It did not change your decision here, but at a closer price it would. %s'
                    % (x['estimate'], p, tip),
                )
        x['error_signed'] = estimate['signed_error'] if estimate else None
        x['coach'] = {
            'kind': kind,
            'verdict': verdict,
            'suggested_stake': rec,
            'clear_odds': clear,
            'estimate': estimate,
        }
        if kind in ('bad_buy', 'missed_edge'):
            flags.append(kind)

    pos_fraction = sum(f for f, x in zip(fractions, result) if x['ev'] > 1e-9)
    full = sum(kelly)
    if growth == -math.inf:
        flags.append('ruin')
        lesson(
            mistakes,
            'bad',
            'Your stakes could wipe out the bankroll',
            'Every bet on a board settles on one outcome, so they can all lose together. Your stakes add up to the whole bankroll, so a single unlucky outcome leaves you with nothing and you cannot recover. '
            'Strategy: keep the total below what the joint worst case can afford; here the suggested total is %.2f.'
            % sum(suggested),
        )
    elif full > 0 and pos_fraction > full + 1e-9:
        flags.append('overbet')
        lesson(
            mistakes,
            'bad',
            'Oversized: %.1f%% of the bankroll on the edges' % (100 * pos_fraction),
            'Full Kelly for this whole board (exact joint outcomes) is %.1f%%; the usual ceiling is half of that, about %.2f units in total. '
            'Staking more buys extra risk for less long-run growth%s. Strategy: size from the joint distribution, not each bet on its own.'
            % (
                100 * full,
                sum(suggested),
                (
                    ', and beyond twice Kelly the average growth turns negative'
                    if pos_fraction > 2 * full
                    else ''
                ),
            ),
        )
    if timed_out:
        flags.append('timeout')
        lesson(
            mistakes,
            'bad',
            'You ran out of time',
            'The deadline passed, so every stake was treated as a pass. Strategy: fix a routine: rank the quotes by break-even, price the easiest proposition first, then size.',
        )
    if not edges:
        if staked == 0 and not timed_out:
            lesson(
                others,
                'good',
                'Correct: nothing here was worth buying',
                'Every price was worse than fair, so passing on the whole board was the best play. Passing is a decision, not a failure to act.',
            )
        elif staked > 0:
            lesson(
                mistakes,
                'bad',
                'This board had no edge to take',
                'Every price was worse than fair, so the best play was to pass on all four propositions. Check break-even on each quote before deciding whether to look for a stake.',
            )
    if mistakes:
        lesson(
            others,
            'tip',
            'Routine for the next board',
            '1) Estimate each probability. 2) Compute break-even = 1/(1+b). 3) Buy only where your probability clearly beats it. 4) Size at most half-Kelly for the whole board, remembering the bets share one outcome. 5) Pass if nothing clears the bar.',
        )
    elif not any(l['tone'] == 'good' for l in others):
        lesson(
            others,
            'good',
            'Sound decision',
            'You bought only prices that beat break-even and kept your sizing in a sensible range. Judge the process, not the single outcome.',
        )
    named = ['%.2f on “%s”' % (rec, x['label']) for x, rec in zip(result, suggested) if rec > 0]
    headline = (
        ('Better play: ' + '; '.join(named) + ' (half-Kelly on the joint distribution).')
        if named
        else 'Better play: pass on the whole board. No price beat its break-even.'
    )
    return {
        'headline': headline,
        'flags': flags,
        'lessons': mistakes + others,
        'suggested': [
            {'id': x['id'], 'label': x['label'], 'stake': rec} for x, rec in zip(result, suggested)
        ],
        'plan_expected': plan['expected'],
        'plan_worst': plan['worst'],
        'plan_loss_probability': plan['loss_probability'],
    }


def training_plan(history):
    """Turn a whole session's round debriefs into a short list of habits to fix."""
    events = [(r['family'], x) for r in history for x in r['events']]
    kinds = collections.Counter(x['coach']['kind'] for _, x in events)
    flags = collections.Counter(f for r in history for f in r['coaching']['flags'])
    focus = []
    bad = [x for _, x in events if x['coach']['kind'] == 'bad_buy']
    if bad:
        focus.append(
            {
                'tone': 'bad',
                'title': 'Stop paying more than fair price',
                'body': 'You staked %.2f units on %d overpriced proposition%s, costing about %.2f units of expected value. Habit: write break-even = 1/(1+b) beside every quote before touching a stake, '
                'and buy only when your probability clears it. A clear buy needs about 10%% better odds than the fair price.'
                % (
                    sum(x['stake'] for x in bad),
                    len(bad),
                    '' if len(bad) == 1 else 's',
                    sum(-x['stake'] * x['ev'] for x in bad),
                ),
            }
        )
    if flags['ruin'] or flags['overbet']:
        focus.append(
            {
                'tone': 'bad',
                'title': 'Size down',
                'body': 'You oversized %d board%s. Bets on one board share an outcome, so their risks add. Stake at most half the joint Kelly amount and check the worst case before locking.'
                % (flags['ruin'] + flags['overbet'], '' if flags['ruin'] + flags['overbet'] == 1 else 's'),
            }
        )
    if flags['estimate_flip']:
        focus.append(
            {
                'tone': 'bad',
                'title': 'Estimates that changed the decision',
                'body': '%d of your probability estimates %s on the wrong side of break-even by at least 3 points. Fix the estimate first, because sizing cannot rescue a wrong call.'
                % (flags['estimate_flip'], 'was' if flags['estimate_flip'] == 1 else 'were'),
            }
        )
    if kinds['missed_edge']:
        edges = sum(x['ev'] > 1e-9 for _, x in events)
        focus.append(
            {
                'tone': 'bad',
                'title': 'Claim the edges you find',
                'body': 'You passed on %d positive-EV proposition%s (%d edges were on offer). Habit: rank quotes by (probability − break-even) and put a small half-Kelly stake on the biggest gap instead of passing.'
                % (kinds['missed_edge'], '' if kinds['missed_edge'] == 1 else 's', edges),
            }
        )
    estimated = [(fam, x) for fam, x in events if x['error_signed'] is not None]
    if estimated:
        bias = sum(x['error_signed'] for _, x in estimated) / len(estimated)
        if abs(bias) >= 3:
            focus.append(
                {
                    'tone': 'tip',
                    'title': 'You %sestimate probabilities' % ('over' if bias > 0 else 'under'),
                    'body': 'On average your estimates were %.1f points %s. Sanity-check with the complement, since the probabilities of an event and its opposite must add to 100%%.'
                    % (abs(bias), 'too high' if bias > 0 else 'too low'),
                }
            )
        by_family = collections.defaultdict(list)
        for fam, x in estimated:
            by_family[fam].append(abs(x['error_signed']))
        fam, errors = max(by_family.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        if sum(errors) / len(errors) >= 8:
            focus.append(
                {
                    'tone': 'tip',
                    'title': 'Weakest topic: ' + FAMILIES[fam]['title'],
                    'body': 'Mean estimate error %.1f points. %s'
                    % (sum(errors) / len(errors), DRILLS[FAMILIES[fam]['topic']]),
                }
            )
    elif history:
        focus.append(
            {
                'tone': 'tip',
                'title': 'Enter probability estimates',
                'body': 'You did not enter any probability estimates, so the review cannot grade the skill that drives every decision. Estimate first, then compare with break-even.',
            }
        )
    if flags['timeout']:
        focus.append(
            {
                'tone': 'bad',
                'title': 'Time management',
                'body': '%d board%s timed out. Fix a routine: rank quotes by break-even, price the easiest proposition first, then size.'
                % (flags['timeout'], '' if flags['timeout'] == 1 else 's'),
            }
        )
    if history and not any(f['tone'] == 'bad' for f in focus):
        focus.insert(
            0,
            {
                'tone': 'good',
                'title': 'Clean session',
                'body': 'No overpriced buys, missed edges, oversized boards or flipped estimates. Raise the difficulty or switch to Interview mode to test yourself without the coach.',
            },
        )
    return focus
