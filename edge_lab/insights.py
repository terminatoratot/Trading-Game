"""Find patterns in a player's past answers and turn them into targeted practice.

The browser keeps a log with one entry per proposition answered (see ``clean_log`` for the
fields). ``profile`` summarises that log into tendencies, such as estimation bias by probability
range, weak topics and bet sizing, and ``practice_focus`` converts the worst of those into
instructions for dealing practice boards.
"""

import collections
import statistics

from .probability import FAMILIES

MAX_LOG = 3000
READY_ESTIMATES = 12  # below this, patterns are mostly noise
BANDS = (('rare', 0, 0.2), ('middle', 0.2, 0.6), ('likely', 0.6, 1.01))
BAND_NAMES = {
    'rare': 'unlikely events (under 20%)',
    'middle': 'mid-range events (20–60%)',
    'likely': 'likely events (over 60%)',
}
DRILL_TEXT = {
    'dice': 'Write out the 6 × 6 grid (or one grid per value of the third die) and count cells rather than guessing.',
    'cards': 'Cards are drawn without replacement: count hands with C(52, n), and use complements ("at least one" = 1 − none).',
    'coins': 'Use binomial counts C(n, k) over the 2^n sequences, and recursions for runs and patterns.',
    'puzzles': 'Look for symmetry first, then complements; when the space is small, list it.',
}


def band(p):
    return next(name for name, lo, hi in BANDS if lo <= p < hi)


def _number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        return None
    return float(value)


def clean_log(raw):
    """Keep well-formed entries only. The log comes from the browser, so nothing is trusted.

    Fields: fam (family key), m (metric), q (question label), p (true probability, 0–1),
    e (estimate in %, or null), h (coach hints used, 0–3), mode, and for betting modes
    be (break-even), ev (EV per unit), k (verdict kind), s and sug (stake and suggested stake
    as fractions of the bankroll).
    """
    entries = []
    for item in (raw if isinstance(raw, list) else [])[-MAX_LOG:]:
        if not isinstance(item, dict) or item.get('fam') not in FAMILIES:
            continue
        p = _number(item.get('p'), 0, 1)
        if p is None:
            continue
        entries.append(
            {
                'fam': item['fam'],
                'm': str(item.get('m', ''))[:40],
                'q': str(item.get('q', ''))[:120],
                'p': p,
                'e': _number(item.get('e'), 0, 100),
                'h': int(_number(item.get('h'), 0, 3) or 0),
                'mode': str(item.get('mode', ''))[:12],
                'be': _number(item.get('be'), 0, 1),
                'ev': _number(item.get('ev'), -1, 1000),
                'k': str(item.get('k') or '')[:16],
                's': _number(item.get('s'), 0, 1),
                'sug': _number(item.get('sug'), 0, 1),
            }
        )
    return entries


def _slope(pairs):
    """Least-squares slope of estimate on truth; 1.0 means estimates track the truth one-for-one."""
    xs = [x for x, _ in pairs]
    if len(pairs) < READY_ESTIMATES or statistics.pvariance(xs) < 25:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(y for _, y in pairs)
    return sum((x - mx) * (y - my) for x, y in pairs) / sum((x - mx) ** 2 for x in xs)


def profile(raw_log):
    log = clean_log(raw_log)
    # A fully revealed walkthrough (hint 3) turns an estimate into copying, so leave those out.
    graded = [x for x in log if x['e'] is not None and x['h'] < 3]
    pairs = [(100 * x['p'], x['e']) for x in graded]
    errors = [e - t for t, e in pairs]

    calibration = []
    for lo in range(0, 100, 10):
        bucket = [(t, e) for t, e in pairs if lo <= t < lo + 10 or (lo == 90 and t == 100)]
        if bucket:
            calibration.append(
                {
                    'lo': lo,
                    'hi': lo + 10,
                    'n': len(bucket),
                    'true': statistics.fmean(t for t, _ in bucket),
                    'est': statistics.fmean(e for _, e in bucket),
                }
            )
    bands = {}
    for name, lo, hi in BANDS:
        errs = [x['e'] - 100 * x['p'] for x in graded if lo <= x['p'] < hi]
        bands[name] = {'n': len(errs), 'bias': statistics.fmean(errs) if errs else 0.0}

    topics = []
    by_family = collections.defaultdict(list)
    for x in graded:
        by_family[x['fam']].append(x)
    for fam, rows in by_family.items():
        abs_err = statistics.fmean(abs(x['e'] - 100 * x['p']) for x in rows)
        calls = [x for x in rows if x['k']]
        wrong = sum(x['k'] in ('bad_buy', 'missed_edge') for x in calls)
        topics.append(
            {
                'family': fam,
                'title': FAMILIES[fam]['title'],
                'n': len(rows),
                'mean_abs': abs_err,
                'wrong_calls': wrong,
                'calls': len(calls),
                'score': abs_err + 20 * (wrong / len(calls) if calls else 0),
            }
        )
    topics.sort(key=lambda t: -t['score'])

    questions = []
    by_question = collections.defaultdict(list)
    for x in graded:
        by_question[(x['fam'], x['m'])].append(x)
    for (fam, metric), rows in by_question.items():
        if len(rows) >= 2:
            questions.append(
                {
                    'family': fam,
                    'metric': metric,
                    'label': rows[-1]['q'],
                    'n': len(rows),
                    'mean_abs': statistics.fmean(abs(x['e'] - 100 * x['p']) for x in rows),
                }
            )
    questions.sort(key=lambda q: -q['mean_abs'])

    bets = [x for x in log if x['k'] and x['ev'] is not None]
    negative = [x for x in bets if x['ev'] < -1e-9]
    positive = [x for x in bets if x['ev'] > 1e-9]
    bad_buys = [x for x in negative if x['k'] == 'bad_buy']
    thin = [x for x in bad_buys if x['be'] is not None and abs(x['p'] - x['be']) <= 0.03]
    missed = [x for x in positive if x['k'] == 'missed_edge']
    ratios = [x['s'] / x['sug'] for x in positive if x['k'] == 'good_buy' and x['s'] and x['sug']]
    coached = [x for x in log if x['mode'] == 'coach' and x['e'] is not None]
    betting = {
        'offered': len(bets),
        'negative': len(negative),
        'bad_buys': len(bad_buys),
        'thin_bad_buys': len(thin),
        'positive': len(positive),
        'missed': len(missed),
        'sized': len(ratios),
        'size_ratio': statistics.median(ratios) if ratios else None,
    }

    result = {
        'estimates': len(graded),
        'ready': len(graded) >= READY_ESTIMATES,
        'need': READY_ESTIMATES,
        'mean_error': statistics.fmean(errors) if errors else None,
        'mean_abs_error': statistics.fmean(abs(e) for e in errors) if errors else None,
        'slope': _slope(pairs),
        'calibration': calibration,
        'points': pairs[-250:],
        'bands': bands,
        'topics': topics[:5],
        'questions': questions[:6],
        'betting': betting,
        'hint_share': sum(x['h'] >= 3 for x in coached) / len(coached) if len(coached) >= 8 else None,
    }
    result['issues'] = issues(result)
    return result


def issues(pr):
    """Rank the patterns worth fixing. Each issue carries a severity so the worst come first."""
    found = []

    def add(key, severity, title, body, tone='bad'):
        found.append({'key': key, 'severity': severity, 'title': title, 'body': body, 'tone': tone})

    for name, data in pr['bands'].items():
        if data['n'] >= 5 and abs(data['bias']) >= 4:
            high = data['bias'] > 0
            add(
                '%s_%s' % ('over' if high else 'under', name),
                abs(data['bias']) / 4,
                'You %sestimate %s' % ('over' if high else 'under', BAND_NAMES[name]),
                'Across %d answers your estimates ran %.1f points too %s. %s'
                % (
                    data['n'],
                    abs(data['bias']),
                    'high' if high else 'low',
                    (
                        'Long shots feel likelier than they are: count the favourable outcomes explicitly.'
                        if high and name == 'rare'
                        else (
                            'Likely events deserve confident numbers: check the complement, which is small and easy to count.'
                            if not high and name == 'likely'
                            else 'Write the fraction down before converting it to a percentage.'
                        )
                    ),
                ),
            )
    slope = pr['slope']
    if slope is not None and slope < 0.85:
        add(
            'compress',
            (1 - slope) * 4,
            'Your estimates drift toward 50%',
            'When the truth is extreme, your answers move toward the middle (slope %.2f; perfect is 1.00). '
            'Trust the count and commit to small or large numbers when the maths says so.' % slope,
        )
    elif slope is not None and slope > 1.2:
        add(
            'extreme',
            (slope - 1) * 4,
            'Your estimates are too extreme',
            'You push answers further from 50%% than the truth (slope %.2f; perfect is 1.00). '
            'Be wary of rounding 30%% down to "unlikely" or 70%% up to "almost certain".' % slope,
        )
    if pr['mean_abs_error'] is not None and pr['mean_abs_error'] >= 8 and pr['estimates'] >= READY_ESTIMATES:
        add(
            'accuracy',
            pr['mean_abs_error'] / 8,
            'Estimates are far off overall',
            'Your average miss is %.1f points. Slow down on the counting: sample space first, favourable cases second.'
            % pr['mean_abs_error'],
            'tip',
        )
    for t in pr['topics'][:2]:
        if t['n'] >= 3 and (t['mean_abs'] >= 8 or (t['calls'] >= 4 and t['wrong_calls'] / t['calls'] >= 0.4)):
            add(
                'topic:' + t['family'],
                t['score'] / 10,
                'Weak spot: ' + t['title'],
                'Average miss %.1f points over %d answers%s. %s'
                % (
                    t['mean_abs'],
                    t['n'],
                    ', with %d wrong calls in %d' % (t['wrong_calls'], t['calls']) if t['calls'] else '',
                    DRILL_TEXT[FAMILIES[t['family']]['topic']],
                ),
            )
    b = pr['betting']
    if b['negative'] >= 6 and b['bad_buys'] / b['negative'] >= 0.25:
        add(
            'bad_buys',
            b['bad_buys'] / b['negative'] * 3,
            'You buy overpriced quotes',
            'You staked on %d of %d negative-EV propositions. Before any stake, compute break-even = 1/(1 + b) '
            'and buy only when your probability clears it.' % (b['bad_buys'], b['negative']),
        )
    if b['bad_buys'] >= 3 and b['thin_bad_buys'] / b['bad_buys'] >= 0.5:
        add(
            'thin_edges',
            1.5,
            'Near-fair prices fool you',
            '%d of your %d overpriced buys were within 3 points of break-even. When the gap is that small, your estimate '
            'error is bigger than the edge, so passing is usually right.'
            % (b['thin_bad_buys'], b['bad_buys']),
        )
    if b['positive'] >= 6 and b['missed'] / b['positive'] >= 0.4:
        add(
            'missed_edges',
            b['missed'] / b['positive'] * 2.5,
            'You leave edges on the table',
            'You passed on %d of %d positive-EV propositions. Rank quotes by (probability − break-even) and put a small '
            'stake on the biggest gap.' % (b['missed'], b['positive']),
        )
    if b['size_ratio'] is not None and b['sized'] >= 4:
        if b['size_ratio'] >= 1.8:
            add(
                'oversize',
                b['size_ratio'] / 1.8,
                'You bet too big',
                'On good buys your typical stake is %.1f× the suggested half-Kelly amount. Bets on one board share an '
                'outcome, so oversizing turns one bad roll into a big drawdown.' % b['size_ratio'],
            )
        elif b['size_ratio'] <= 0.4:
            add(
                'undersize',
                0.4 / max(b['size_ratio'], 0.05),
                'You bet too small',
                'On good buys your typical stake is only %.1f× the suggested half-Kelly amount. Finding edges only pays '
                'if you back them.' % b['size_ratio'],
                'tip',
            )
    if pr['hint_share'] is not None and pr['hint_share'] >= 0.5:
        add(
            'hints',
            1,
            'You lean on the full walkthrough',
            'You opened the full walkthrough on %.0f%% of Coach questions. Try stopping at the first hint.'
            % (100 * pr['hint_share']),
            'tip',
        )
    found.sort(key=lambda x: -x['severity'])
    return found


def practice_focus(pr):
    """Turn a profile into dealing instructions for a targeted practice session."""
    keys = [i['key'] for i in pr['issues']]
    families = {}
    for weight, t in zip((4, 3, 2), [t for t in pr['topics'] if t['n'] >= 3]):
        families[t['family']] = weight
    bands = sorted({k.split('_', 1)[1] for k in keys if k.split('_', 1)[0] in ('over', 'under')})
    if 'compress' in keys or 'extreme' in keys:
        bands = sorted(set(bands) | {'rare', 'likely'})
    prices = []
    if 'bad_buys' in keys or 'thin_edges' in keys:
        prices.append('thin')
    if 'missed_edges' in keys:
        prices.append('positive')
    if 'oversize' in keys or 'undersize' in keys:
        prices.append('clear')
    return {
        'families': families,
        'questions': [[q['family'], q['metric']] for q in pr['questions'] if q['mean_abs'] >= 6],
        'bands': bands,
        'prices': prices,
        'labels': [i['title'] for i in pr['issues'][:3]],
    }
