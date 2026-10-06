"""Single-player sessions: dealing boards, validating bets and settling them."""

import collections
import csv
import io
import math
import random
import secrets
import time

from .insights import BAND_NAMES, band
from .coaching import coach_round, training_plan, win_patterns
from .probability import FAMILIES, TOPICS, analyse, event_bank, explanation, sample_space, wins

LEVEL = {'easy': 1, 'medium': 2, 'hard': 3}


def dealable(family, level, count):
    """A board suits a level if at least two of its questions are at that level and it can fill a board
    using that level plus the one below (easy boards use easy questions only)."""
    levels = [e['level'] for e in event_bank(family)]
    exact = levels.count(level)
    return exact >= min(2, count) and exact + (levels.count(level - 1) if level > 1 else 0) >= count


TOLERANCE = {'easy': 10, 'medium': 5, 'hard': 2}  # accepted probability error, in percentage points


BOARD_SIZE = {'easy': 3, 'medium': 4, 'hard': 4}
MISPRICING = {
    'easy': (0.14, 0.32),
    'medium': (0.07, 0.22),
    'hard': (0.015, 0.10),
}  # relative error in quoted odds


def focus_score(family, e, focus):
    """How well a question matches a practice focus: 2 for a weak question type, 1 for a weak probability range."""
    if not focus:
        return 0
    return 2 * ([family, e['metric']] in focus.get('questions', [])) + (
        band(e['p']) in focus.get('bands', [])
    )


def choose_board(rng, difficulty, topic, count, focus=None):
    """Pick a family and `count` questions for it. A focus tilts both choices toward the player's weak spots."""
    level = LEVEL[difficulty]
    weights = (focus or {}).get('families', {})
    levels = {}
    for f, spec in FAMILIES.items():
        if topic not in ('mixed', spec['topic']):
            continue
        if dealable(f, level, count):
            levels[f] = level
        elif weights.get(f, 1) > 1:
            # A weak topic is worth practising even if it lives at another level: use the nearest one.
            near = [
                lv for lv in sorted(LEVEL.values(), key=lambda lv: abs(lv - level)) if dealable(f, lv, count)
            ]
            if near:
                levels[f] = near[0]
    families = list(levels)
    family = rng.choices(families, [weights.get(f, 1) for f in families])[0]
    level = levels[family]
    # Questions at the chosen level first; top up from one level easier only when a board runs short.
    pools = [[e for e in event_bank(family) if e['level'] == lv] for lv in (level, level - 1)]
    targeted = [e for e in pools[0] + pools[1] if focus_score(family, e, focus) > 0]
    selected = []

    def take(pool, limit):
        while pool and len(selected) < limit:
            # Sample across event types, preventing product thresholds from dominating.
            keys = sorted({e['metric'] for e in pool})
            used = {e['metric'] for e in selected}
            metric = rng.choice([k for k in keys if k not in used] or keys)
            e = dict(rng.choice([e for e in pool if e['metric'] == metric]))
            for other in pools + [targeted]:
                other[:] = [x for x in other if x['label'] != e['label']]
            selected.append(e)

    take(targeted, min(2, count))
    for pool in pools:
        take(pool, count)
    return family, selected


def price_board(rng, events, difficulty, focus=None):
    """Quote profit odds around the fair price. Practice prices can lean thin, generous or clearly positive."""
    low, high = MISPRICING[difficulty]
    prices = (focus or {}).get('prices', [])
    count = len(events)
    if rng.random() < 0.15 and not prices:
        signs = [-1] * count
    else:
        signs = [1, -1] + [rng.choice([-1, 1]) for _ in range(count - 2)]
    if 'positive' in prices:
        signs = [1, 1, -1] + [rng.choice([-1, 1]) for _ in range(count - 3)]
    rng.shuffle(signs)
    for i, (e, sign) in enumerate(zip(events, signs)):
        lo, hi = low, high
        if sign < 0 and 'thin' in prices:
            lo, hi = 0.02, 0.07  # overpriced by only a little: the trap to practise passing on
        elif sign > 0 and 'clear' in prices:
            lo, hi = 0.2, 0.35  # clearly good, so the question becomes how much to stake
        fair = (1 - e['p']) / e['p']
        e['odds'] = max(0.01, round(fair * (1 + sign * rng.uniform(lo, hi)), 2))
        e['id'] = str(i)
    return events


PRICE_NOTES = {'thin': 'near-fair prices', 'positive': 'several real edges', 'clear': 'clear edges to size'}


def focus_note(family, events, focus):
    """One line telling the player what this board is testing: at most one phrase per kind of target."""
    if not focus:
        return None
    parts = []
    if focus.get('families', {}).get(family, 1) > 1:
        parts.append('a weak topic for you')
    ranges = []
    for name in focus.get('bands', []):
        n = sum(band(e['p']) == name for e in events)
        if n:
            ranges.append('%d %s' % (n, BAND_NAMES[name].split(' ')[0]))
    if ranges:
        count = sum(int(r.split()[0]) for r in ranges)
        parts.append(' and '.join(ranges) + (' event' if count == 1 else ' events'))
    if any([family, e['metric']] in focus.get('questions', []) for e in events):
        parts.append('a question type you have missed before')
    prices = [PRICE_NOTES[p] for p in focus.get('prices', []) if p in PRICE_NOTES]
    if prices:
        parts.append(' and '.join(prices))
    return (
        'This board targets: ' + ', '.join(parts) + '.'
        if parts
        else 'A general board to check your progress.'
    )


def board_public(family, number):
    """What the page needs to draw a board, without any answers."""
    spec = FAMILIES[family]
    return {
        'number': number,
        'family': family,
        'title': spec['title'],
        'rules': spec['rules'],
        'kind': spec['kind'],
        'count': spec['n'],
        'topic': spec['topic'],
        'slots': spec.get('slots') or ['?'] * spec['n'],
    }


def finite_number(value, name, lo, hi):
    if isinstance(value, bool):
        raise ValueError('%s must be a number.' % name)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError('%s must be a number.' % name)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError('%s must be between %s and %s.' % (name, lo, hi))
    return value


class Session:
    def __init__(self, cfg):
        self.mode = cfg.get('mode', 'coach')
        self.difficulty = cfg.get('difficulty', 'medium')
        self.topic = cfg.get('topic', 'mixed')
        if self.mode not in ('coach', 'interview', 'sprint', 'practice'):
            raise ValueError('Unknown mode.')
        if self.difficulty not in ('easy', 'medium', 'hard'):
            raise ValueError('Unknown difficulty.')
        if self.topic not in ('mixed',) + TOPICS:
            raise ValueError('Unknown topic.')
        self.tolerance = TOLERANCE[self.difficulty]
        self.focus = cfg.get('focus') if self.mode == 'practice' else None
        self.start_bank = round(finite_number(cfg.get('bankroll', 1000), 'Bankroll', 10, 1000000), 2)
        self.bank = self.start_bank
        self.rounds = int(finite_number(cfg.get('rounds', 10), 'Rounds', 1, 100))
        self.seconds = finite_number(cfg.get('seconds', 60), 'Seconds', 10, 600)
        self.minutes = finite_number(cfg.get('minutes', 10), 'Minutes', 1, 60)
        self.seed = str(cfg.get('seed') or secrets.token_hex(4))[:80]
        self.rng = random.Random(self.seed + '/quotes')
        self.outcome_rng = random.Random(self.seed + '/outcomes')
        self.id = secrets.token_urlsafe(20)
        self.created = time.monotonic()
        self.deadline = self.created + self.minutes * 60 if self.mode == 'sprint' else None
        self.history = []
        self.current = None
        self.finished = False
        self.ended = False
        self.abandoned = False
        self.next_round()

    def end(self):
        """Close the session and return its summary. Ending before the last round (or the sprint clock) is abandonment."""
        if not self.ended:
            self.abandoned = not (self.finished or self.expired())
            self.ended = True
        self.finished = True
        return self.summary()

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline

    def next_round(self):
        if self.current is not None and not self.current.get('settled'):
            raise ValueError('Settle the current round first.')
        if (
            self.finished
            or self.expired()
            or self.bank < 0.01
            or (self.mode != 'sprint' and len(self.history) >= self.rounds)
        ):
            self.finished = True
            return
        family, selected = choose_board(
            self.rng, self.difficulty, self.topic, BOARD_SIZE[self.difficulty], self.focus
        )
        price_board(self.rng, selected, self.difficulty, self.focus)
        now = time.monotonic()
        deadline = now + self.seconds if self.mode == 'interview' else self.deadline
        self.current = {
            'number': len(self.history) + 1,
            'family': family,
            'events': selected,
            'started': now,
            'deadline': deadline,
            'settled': False,
            'focus_note': focus_note(family, selected, self.focus),
        }

    def public(self):
        r = self.current
        now = time.monotonic()
        payload = {
            'id': self.id,
            'mode': self.mode,
            'difficulty': self.difficulty,
            'topic': self.topic,
            'seed': self.seed,
            'bank': self.bank,
            'tolerance': self.tolerance,
            'start_bank': self.start_bank,
            'rounds': self.rounds,
            'finished': self.finished,
            'completed': len(self.history),
            'session_remaining': max(0, self.deadline - now) if self.deadline else None,
        }
        if not self.finished and r:
            events = []
            for e in r['events']:
                item = {k: e[k] for k in ('id', 'label', 'odds')}
                if self.mode == 'coach':
                    item['answer'] = dict(analyse(e), **explanation(r['family'], e))
                events.append(item)
            payload['round'] = dict(
                board_public(r['family'], r['number']),
                events=events,
                settled=r['settled'],
                focus_note=r['focus_note'],
                remaining=max(0, r['deadline'] - now) if r['deadline'] else None,
            )
        return payload

    def parse_bets(self, data):
        """Validate a submission for the current board without settling it: (stakes, estimates, timed_out)."""
        r = self.current
        if self.finished or not r or r['settled']:
            raise ValueError('This round is already closed.')
        if data.get('round') != r['number']:
            raise ValueError('The submitted round does not match the current round.')
        raw_stakes, raw_estimates = data.get('stakes', {}), data.get('estimates', {})
        if not isinstance(raw_stakes, dict) or not isinstance(raw_estimates, dict):
            raise ValueError('Invalid bets.')
        stakes = [
            round(finite_number(raw_stakes.get(e['id'], 0), 'Stake', 0, self.bank), 2) for e in r['events']
        ]
        estimates = []
        for e in r['events']:
            value = raw_estimates.get(e['id'])
            estimates.append(
                None if value is None or value == '' else finite_number(value, 'Probability estimate', 0, 100)
            )
        if sum(stakes) > self.bank + 1e-7:
            raise ValueError('Total stakes cannot exceed your bankroll.')
        # A small transport allowance for a client submitting at countdown zero.
        timed_out = r['deadline'] is not None and time.monotonic() > r['deadline'] + 2
        auto = data.get('auto') is True  # the client's deadline auto-submit may leave estimates blank
        if not timed_out and not auto and any(v is None for v in estimates):
            raise ValueError('Enter a probability estimate (0 to 100%) for every proposition.')
        return stakes, estimates, timed_out

    def settle(self, data):
        r = self.current
        stakes, estimates, timed_out = self.parse_bets(data)
        if timed_out:
            stakes = [0] * len(stakes)
        outcomes, rows = sample_space(r['family'])
        index = self.outcome_rng.randrange(len(outcomes))
        outcome, actual = outcomes[index], rows[index]
        result = []
        for e, stake, estimate in zip(r['events'], stakes, estimates):
            a = analyse(e)
            won = wins(e, actual)
            profit = round(stake * (e['odds'] if won else -1), 2)
            result.append(
                dict(
                    e,
                    **{k: v for k, v in a.items() if k not in e},
                    explanation=explanation(r['family'], e),
                    stake=stake,
                    estimate=estimate,
                    won=won,
                    profit=profit,
                    expected_profit=stake * a['ev'],
                    error_pp=abs(estimate - 100 * e['p']) if estimate is not None else None,
                    within_range=(
                        abs(estimate - 100 * e['p']) <= self.tolerance + 1e-9
                        if estimate is not None
                        else None
                    )
                )
            )
        # Joint distribution uses ONE shared outcome per board, preserving dependence.
        pnl_distribution = [
            sum(stake * (e['odds'] if wins(e, row) else -1) for e, stake in zip(r['events'], stakes))
            for row in rows
        ]
        pnl = round(sum(x['profit'] for x in result), 2)
        expected = sum(x['expected_profit'] for x in result)
        total = sum(stakes)
        positive = sum(x['stake'] * max(0, x['ev']) for x in result)
        negative = sum(x['stake'] * max(0, -x['ev']) for x in result)
        fraction_wrong = sum(x['stake'] for x in result if x['ev'] < -1e-9)
        coaching = coach_round(
            r['events'], result, self.bank, timed_out, win_patterns(r['events'], rows), self.tolerance
        )
        self.bank = round(self.bank + pnl, 2)
        spec = FAMILIES[r['family']]
        dist_metric, dist_label = spec['hist']
        freq = collections.Counter(row[dist_metric] for row in rows)
        probabilities = [dict(value=k, probability=v / len(rows)) for k, v in sorted(freq.items())]
        labels, reds = spec['tokens'](outcome)
        record = {
            'round': r['number'],
            'family': r['family'],
            'title': spec['title'],
            'bank_before': round(self.bank - pnl, 2),
            'bank_after': self.bank,
            'profit': pnl,
            'expected_profit': expected,
            'staked': total,
            'events': result,
            'outcome': labels,
            'outcome_red': reds,
            'token_style': spec['style'],
            'outcome_note': spec['note'](outcome, actual),
            'dist_label': dist_label,
            'dist_value': actual[dist_metric],
            'seconds': time.monotonic() - r['started'],
            'worst': min(pnl_distribution),
            'best': max(pnl_distribution),
            'loss_probability': sum(x < -1e-8 for x in pnl_distribution) / len(rows),
            'negative_ev_stake': fraction_wrong,
            'positive_ev': positive,
            'negative_ev': negative,
            'timed_out': timed_out,
            'distribution': probabilities,
            'coaching': coaching,
            'tolerance': self.tolerance,
            'estimates_in_range': sum(x['within_range'] is True for x in result),
        }
        r['settled'] = True
        self.history.append(record)
        if self.expired() or self.bank < 0.01 or (self.mode != 'sprint' and len(self.history) >= self.rounds):
            self.finished = True
        return record

    def summary(self):
        events = [e for r in self.history for e in r['events']]
        errors = [e['error_pp'] for e in events if e['error_pp'] is not None]
        staked = sum(r['staked'] for r in self.history)
        bad_stakes = sum(r['negative_ev_stake'] for r in self.history)
        taken = [e for e in events if e['stake'] > 0]
        edges = [e for e in events if e['ev'] > 1e-9]
        path = [self.start_bank] + [r['bank_after'] for r in self.history]
        peak, drawdown = path[0], 0
        for value in path:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        return {
            'id': self.id,
            'abandoned': self.abandoned,
            'focus': self.focus,
            'seed': self.seed,
            'mode': self.mode,
            'difficulty': self.difficulty,
            'topic': self.topic,
            'start_bank': self.start_bank,
            'bank': self.bank,
            'profit': self.bank - self.start_bank,
            'rounds': len(self.history),
            'expected_profit': sum(r['expected_profit'] for r in self.history),
            'negative_ev_stake_pct': 100 * bad_stakes / staked if staked else None,
            'positive_bets': sum(e['ev'] > 1e-9 for e in taken),
            'bets': len(taken),
            'edges_taken': sum(e['stake'] > 0 for e in edges),
            'edges_available': len(edges),
            'mean_error_pp': sum(errors) / len(errors) if errors else None,
            'estimates': len(errors),
            'max_drawdown': drawdown,
            'tolerance': self.tolerance,
            'estimates_in_range': sum(e['within_range'] is True for e in events),
            'estimates_total': len(events),
            'mean_seconds': (
                sum(r['seconds'] for r in self.history) / len(self.history) if self.history else 0
            ),
            'path': path,
            'history': self.history,
            'coaching': {'focus': training_plan(self.history)},
        }

    def csv(self):
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(
            [
                'seed',
                'mode',
                'difficulty',
                'round',
                'family',
                'event',
                'profit_odds',
                'true_probability',
                'estimated_probability_pct',
                'estimate_in_range',
                'stake',
                'ev_per_unit',
                'expected_profit',
                'won',
                'realised_profit',
                'bank_after',
                'decision_seconds',
            ]
        )
        for r in self.history:
            for e in r['events']:
                # Prefix possible formula characters in a user-supplied seed for spreadsheet safety.
                seed = self.seed if self.seed[:1] not in '=+-@\t\r' else "'" + self.seed
                writer.writerow(
                    [
                        seed,
                        self.mode,
                        self.difficulty,
                        r['round'],
                        r['family'],
                        e['label'],
                        e['odds'],
                        e['p'],
                        e['estimate'],
                        e['within_range'],
                        e['stake'],
                        e['ev'],
                        e['expected_profit'],
                        e['won'],
                        e['profit'],
                        r['bank_after'],
                        r['seconds'],
                    ]
                )
        return output.getvalue()


class Drill:
    """Quick-fire pricing: one question at a time, no odds or stakes, against a single clock.

    Each answer is graded against the difficulty's tolerance and feeds a streak. Answers that
    arrive after the clock (plus a transport allowance) are not scored.
    """

    GRACE = 2

    def __init__(self, cfg, focus=None):
        self.difficulty = cfg.get('difficulty', 'medium')
        self.topic = cfg.get('topic', 'mixed')
        if self.difficulty not in LEVEL:
            raise ValueError('Unknown difficulty.')
        if self.topic not in ('mixed',) + TOPICS:
            raise ValueError('Unknown topic.')
        self.tolerance = TOLERANCE[self.difficulty]
        self.seconds = finite_number(cfg.get('seconds', 120), 'Drill length', 30, 900)
        self.focus = focus
        self.rng = random.Random(secrets.token_hex(8))
        self.id = secrets.token_urlsafe(20)
        self.deadline = time.monotonic() + self.seconds
        self.answers = []
        self.streak = self.best = 0
        self.finished = False
        self.question = None
        self.next_question()

    def expired(self):
        return time.monotonic() > self.deadline + self.GRACE

    def next_question(self):
        family, (e,) = choose_board(self.rng, self.difficulty, self.topic, 1, self.focus)
        self.question = {
            'number': len(self.answers) + 1,
            'family': family,
            'event': e,
            'started': time.monotonic(),
        }

    def public(self):
        q = self.question
        payload = {
            'id': self.id,
            'difficulty': self.difficulty,
            'topic': self.topic,
            'tolerance': self.tolerance,
            'remaining': max(0, self.deadline - time.monotonic()),
            'answered': len(self.answers),
            'correct': sum(a['within'] for a in self.answers),
            'streak': self.streak,
            'best': self.best,
            'finished': self.finished,
        }
        if q and not self.finished:
            payload['question'] = dict(
                board_public(q['family'], q['number']),
                label=q['event']['label'],
                focus_note=focus_note(q['family'], [q['event']], self.focus and dict(self.focus, prices=[])),
            )
        return payload

    def answer(self, data):
        q = self.question
        if self.finished or q is None:
            raise ValueError('This drill has finished.')
        if data.get('number') != q['number']:
            raise ValueError('That answer is for a different question.')
        estimate = finite_number(data.get('estimate'), 'Probability estimate', 0, 100)
        if self.expired():
            self.finished = True
            return {'feedback': None, 'drill': self.public()}
        e = q['event']
        error = estimate - 100 * e['p']
        within = abs(error) <= self.tolerance + 1e-9
        self.streak = self.streak + 1 if within else 0
        self.best = max(self.best, self.streak)
        feedback = dict(
            explanation(q['family'], e),
            label=e['label'],
            title=FAMILIES[q['family']]['title'],
            family=q['family'],
            metric=e['metric'],
            p=e['p'],
            estimate=estimate,
            error=error,
            within=within,
            seconds=time.monotonic() - q['started'],
        )
        self.answers.append(feedback)
        if time.monotonic() > self.deadline:
            self.finished = True
        else:
            self.next_question()
        return {'feedback': feedback, 'drill': self.public()}

    def summary(self):
        self.finished = True
        answers = self.answers
        misses = sorted((a for a in answers if not a['within']), key=lambda a: -abs(a['error']))
        return {
            'id': self.id,
            'difficulty': self.difficulty,
            'topic': self.topic,
            'tolerance': self.tolerance,
            'seconds': self.seconds,
            'answered': len(answers),
            'correct': sum(a['within'] for a in answers),
            'best': self.best,
            'mean_abs_error': sum(abs(a['error']) for a in answers) / len(answers) if answers else None,
            'mean_seconds': sum(a['seconds'] for a in answers) / len(answers) if answers else None,
            'misses': misses[:6],
            'answers': answers,
        }
