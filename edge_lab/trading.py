"""A market-making card game against bots.

Each round a hand of cards is dealt and some of it is turned face up. Cards are worth 2 to 14 (J=11,
Q=12, K=13, A=14) and the hand settles at the sum of their values unless a market event changes the
rule. One player makes a two-way market, "X at Y": a bid X and an ask Y whose gap (the spread) must
fall within the table's limits. Every other player may buy at the ask, sell at the bid, or pass.
When the hand is revealed, buyers make (value − ask) per unit and sellers make (bid − value); the
market maker takes the other side of every trade.

Orders must be affordable: a long position must be payable from your balance, and a short position's
worst possible loss must be covered by it. In rotational mode the market maker takes turns; in open
outcry everyone races to shout a quote and the first valid one makes the market.

Market events change the deck, the settlement rule or what some players know. Easy events only
change which cards can be dealt; harder ones change the payoff, add conditional news, let a bot see a
hidden card, or stack two events together. Fair values are exact averages over every possible hidden
hand (or a large fixed sample when there are too many hands to list).
"""

import itertools
import json
import math
import random
import secrets
import statistics
import time
from pathlib import Path

SUITS = '♣♦♥♠'
DECK = range(52)
NAMES = {11: 'J', 12: 'Q', 13: 'K', 14: 'A'}
BOT_UNITS = 10  # bots never trade more than this in one order
UNIT_CAP = 100  # a sanity cap on any single order
CHECK_PENALTY = 50
EXACT_LIMIT = 60_000  # list every hidden hand up to this many, otherwise sample
SAMPLES = 40_000
GRACE = 2  # seconds allowed for a request racing the round clock
LEADERBOARD = Path(__file__).resolve().parent.parent / 'edge_lab_data' / 'leaderboard.json'


def rank(c):
    """Card value: 2 … 10, J=11, Q=12, K=13, A=14."""
    return c % 13 + 2


def suit(c):
    return c // 13


def is_red(c):
    return suit(c) in (1, 2)


def is_face(c):
    return 11 <= rank(c) <= 13


def card_label(c):
    return NAMES.get(rank(c), str(rank(c))) + SUITS[suit(c)]


def total(cards):
    return sum(rank(c) for c in cards)


# ---- Market events ---------------------------------------------------------------------------
#
# An event is a dict with:
#   text     what the players are told
#   lesson   one line explaining what the event does to fair value, shown after the round
#   deck     which cards can be dealt (None: the whole deck)
#   value    settlement rule for the whole hand (None: the sum of the card values)
#   news     a fact about the hidden cards that the deal is guaranteed to satisfy
#   insider  whether one bot secretly sees a hidden card
#
# A full deck averages 8 per card, which is the baseline every lesson compares against.


def event(key, text, lesson, deck=None, value=None, news=None, insider=False, rule=None, **params):
    """`rule` names how the event changes the price, for the worked explanation; `params` hold its numbers."""
    if rule is None and (value or news or insider):
        rule = key
    return {
        'key': key,
        'text': text,
        'lesson': lesson,
        'deck': deck,
        'value': value,
        'news': news,
        'insider': insider,
        'rule': rule,
        'params': params,
    }


EASY = [
    event(
        'even',
        'Only even cards this round.',
        'Even cards (2, 4, …, Q, A) average 8, the same as a full deck, so fair value hardly moves.',
        deck=lambda c: rank(c) % 2 == 0,
    ),
    event(
        'odd',
        'Only odd cards this round.',
        'Odd cards (3, 5, …, K) also average 8: the headline sounds big but fair value barely changes.',
        deck=lambda c: rank(c) % 2 == 1,
    ),
    event(
        'no_faces',
        'No face cards this round: J, Q and K are removed.',
        'Without J, Q and K the average card falls from 8 to 6.8 (the ace still counts 14).',
        deck=lambda c: not is_face(c),
    ),
    event(
        'high',
        'Only cards 8 and above this round.',
        'Cards 8 to A average 11, so each hidden card is worth 3 more than usual.',
        deck=lambda c: rank(c) >= 8,
    ),
    event(
        'low',
        'Only cards 7 and below this round.',
        'Cards 2 to 7 average 4.5, so each hidden card is worth 3.5 less than usual.',
        deck=lambda c: rank(c) <= 7,
    ),
    event(
        'bonus',
        'Settlement is the card total plus 10.',
        'A fixed bonus moves fair value by exactly 10. The uncertainty is unchanged, so the spread should be too.',
        value=lambda cs: total(cs) + 10,
    ),
    event(
        'red',
        'All cards this round are red.',
        'Colour does not change value: red cards average 8 like any others. Not every headline matters.',
        deck=is_red,
    ),
]

MEDIUM = [
    event(
        'ace_low',
        'Aces count as 1 this round.',
        'An ace loses 13 and is 1 card in 13, so each hidden card is worth 1 less on average.',
        value=lambda cs: sum(1 if rank(c) == 14 else rank(c) for c in cs),
    ),
    event(
        'blackjack',
        'Face cards count as 10 and aces as 11.',
        'J, Q, K lose 1, 2, 3 and the ace loses 3: the average card falls to 7.31, about −0.7 per hidden card.',
        value=lambda cs: sum(11 if rank(c) == 14 else min(rank(c), 10) for c in cs),
    ),
    event(
        'double_high',
        'The highest card counts double.',
        'Fair value rises by the expected highest card, which is well above 8 when several cards are dealt.',
        value=lambda cs: total(cs) + max(rank(c) for c in cs),
    ),
    event(
        'drop_low',
        'The lowest card is removed from the total.',
        'Fair value falls by the expected lowest card, which is well below 8.',
        value=lambda cs: total(cs) - min(rank(c) for c in cs),
    ),
    event(
        'hearts_double',
        'Hearts count double.',
        'A quarter of cards are hearts, so each hidden card gains 8 × 1/4 = 2 on average.',
        value=lambda cs: total(cs) + sum(rank(c) for c in cs if suit(c) == 2),
    ),
    event(
        'pair_bonus',
        'If any two cards share a rank, add 20 to the settlement.',
        'Fair value rises by 20 × P(a pair), which grows quickly with the number of cards.',
        value=lambda cs: total(cs) + (20 if len({rank(c) for c in cs}) < len(cs) else 0),
    ),
    event(
        'face_news',
        'News: at least one hidden card is a face card (J, Q or K).',
        'Conditioning on "at least one" lifts every hidden card a little, not just one card to 12.',
        news=lambda hidden: any(is_face(c) for c in hidden),
    ),
]


def hard_events(n):
    """Hard events depend on the hand size, so build them per game."""
    cap, floor = 8 * n + 2, 8 * n - 6
    return [
        event(
            'red_minus_black',
            'Settlement = red cards minus black cards.',
            'Red and black cancel on average, so fair value sits near zero apart from the cards you can see, '
            'but the range of outcomes is huge: quote wide.',
            value=lambda cs: sum(rank(c) if is_red(c) else -rank(c) for c in cs),
        ),
        event(
            'cap',
            'Settlement is capped at %d.' % cap,
            'A cap removes the best outcomes, so fair value is below the uncapped average. Price it like a sold call.',
            value=lambda cs: min(total(cs), cap),
            cap=cap,
        ),
        event(
            'collar',
            'Settlement is floored at %d and capped at %d.' % (floor, cap),
            'A collar squeezes both tails: fair value stays near the middle and the spread can be tighter.',
            value=lambda cs: min(max(total(cs), floor), cap),
            cap=cap,
            floor=floor,
        ),
        event(
            'high_times',
            'Settlement is the highest card times %d.' % n,
            'Only the maximum matters: one high card anywhere decides the price, so fair value is high and skewed.',
            value=lambda cs: n * max(rank(c) for c in cs),
            n=n,
        ),
        event(
            'odd_half',
            'If the total is odd, the settlement is halved (rounded down).',
            'About half of outcomes are cut in half: fair value drops by roughly a quarter.',
            value=lambda cs: total(cs) // 2 if total(cs) % 2 else total(cs),
        ),
        event(
            'insider',
            'One bot has seen a hidden card. Watch how it trades.',
            'Trades from an informed player are evidence. Widen your spread, and lean away from the side the insider wants.',
            insider=True,
        ),
        event(
            'face_news',
            'News: at least one hidden card is a face card (J, Q or K).',
            'Conditioning on "at least one" lifts every hidden card a little, not just one card to 12.',
            news=lambda hidden: any(is_face(c) for c in hidden),
        ),
    ]


def stacked(rng, n):
    """Hard rounds can combine a deck change with a payoff change."""
    base = rng.choice([e for e in EASY if e['deck']])
    rule = rng.choice([e for e in MEDIUM if e['value']])
    return event(
        base['key'] + '+' + rule['key'],
        base['text'] + ' ' + rule['text'],
        base['lesson'] + ' ' + rule['lesson'],
        deck=base['deck'],
        value=rule['value'],
        rule=rule['rule'],
        deck_key=base['key'],
        **rule['params'],
    )


def draw_event(rng, tier, n):
    """Pick the round's event. Higher tiers mostly draw harder events, sometimes easier ones."""
    roll = rng.random()
    if tier == 'easy':
        return None if roll < 0.3 else rng.choice(EASY)
    if tier == 'medium':
        return None if roll < 0.1 else rng.choice(EASY) if roll < 0.35 else rng.choice(MEDIUM)
    if roll < 0.3:
        return rng.choice(MEDIUM)
    if roll < 0.55:
        return stacked(rng, n)
    return rng.choice(hard_events(n))


# ---- Fair value -------------------------------------------------------------------------------


def settle(ev, cards):
    return (ev['value'] if ev and ev['value'] else total)(cards)


def hidden_pool(ev, seen):
    deck_ok = (ev or {}).get('deck') or (lambda c: True)
    return [c for c in DECK if deck_ok(c) and c not in seen]


def outcomes(ev, known, hidden_count, seed=0):
    """Every settlement value consistent with the known cards, one per equally likely hidden hand.

    `known` are cards the player can see; the other `hidden_count` cards come from the rest of the
    event's deck. News about the hidden cards is applied by keeping only hands that match.
    """
    news = (ev or {}).get('news')
    pool = hidden_pool(ev, known)
    if math.comb(len(pool), hidden_count) <= EXACT_LIMIT:
        hands = itertools.combinations(pool, hidden_count)
    else:
        rng = random.Random(seed)
        hands = (rng.sample(pool, hidden_count) for _ in range(SAMPLES))
    return [settle(ev, list(known) + list(h)) for h in hands if news is None or news(tuple(h))]


def fair_value(ev, known, hidden_count, seed=0, insider_card=None):
    """Mean, spread and range of the settlement given what a player knows."""
    seen = list(known) + ([insider_card] if insider_card is not None else [])
    remaining = hidden_count - (insider_card is not None)
    if insider_card is not None and ev and ev.get('news'):
        values = outcomes(dict(ev, news=lambda h: ev['news'](h + (insider_card,))), seen, remaining, seed)
    else:
        values = outcomes(ev, seen, remaining, seed)
    pool = sorted(hidden_pool(ev, seen), key=rank)
    # Sampling can miss the extremes, so also price the highest and lowest hands directly.
    top = settle(ev, seen + pool[-remaining:]) if remaining else settle(ev, seen)
    bottom = settle(ev, seen + pool[:remaining]) if remaining else settle(ev, seen)
    return {
        'mean': statistics.fmean(values),
        'sd': statistics.pstdev(values),
        'max': max(max(values), top, bottom),
        'min': min(min(values), top, bottom),
        'hands': len(values),
        'exact': math.comb(len(pool), remaining) <= EXACT_LIMIT,
    }


def order_limits(balance, bid, ask, worst_high, worst_low):
    """Largest affordable orders: a long must be paid for, a short's worst loss must be covered."""
    if balance <= 0:
        return {'buy': 0, 'sell': 0}
    long_unit = max(ask, ask - worst_low, 1)
    short_unit = max(worst_high - bid, 1)
    return {
        'buy': min(UNIT_CAP, int(balance // long_unit)),
        'sell': min(UNIT_CAP, int(balance // short_unit)),
    }


# ---- Worked explanations ---------------------------------------------------------------------
#
# After each round the player sees how fair value was built: first the plain sum without the event,
# then exactly what the event changes, with the round's own numbers. Steps carry LaTeX for the page.

DECK_TEXT = {
    'even': 'only even cards can be dealt (2, 4, …, Q, A)',
    'odd': 'only odd cards can be dealt (3, 5, …, K)',
    'no_faces': 'J, Q and K are removed (2–10 and A remain)',
    'high': 'only cards 8 to A can be dealt',
    'low': 'only cards 2 to 7 can be dealt',
    'red': 'only red cards can be dealt (their values are unchanged)',
}
CARD_RULES = {  # per-card value changes: (function, how the page writes it)
    'ace_low': (
        lambda c: 1 if rank(c) == 14 else rank(c),
        r'f(\text{A}) = 1,\ \text{otherwise } f(c) = \text{value}',
    ),
    'blackjack': (
        lambda c: 11 if rank(c) == 14 else min(rank(c), 10),
        r'f(\text{J}) = f(\text{Q}) = f(\text{K}) = 10,\ f(\text{A}) = 11',
    ),
    'hearts_double': (
        lambda c: 2 * rank(c) if suit(c) == 2 else rank(c),
        r'f(c) = 2v \text{ for hearts},\ v \text{ otherwise}',
    ),
    'red_minus_black': (
        lambda c: rank(c) if is_red(c) else -rank(c),
        r'f(c) = +v \text{ if red},\ -v \text{ if black}',
    ),
}


def n2(x):
    return '%.2f' % x


def step(label, words, tex):
    return {'label': label, 'words': words, 'tex': tex}


def explain(ev, shown, k, seed, public):
    """Derive this round's fair value step by step. Returns a summary sentence and the steps."""
    ev = ev or {}
    eq = '=' if public['exact'] else r'\approx'
    visible = total(shown)
    deck_key = ev.get('params', {}).get('deck_key') or (
        ev.get('key') if ev.get('deck') and not ev.get('rule') else None
    )
    full = [c for c in DECK if c not in shown]
    pool = hidden_pool(ev, shown)
    steps = []

    def sum_step(cards, label, words):
        total_left = sum(rank(c) for c in cards)
        avg = total_left / len(cards)
        mean = visible + k * avg
        lead = r'\underbrace{%d}_{\text{visible}} + ' % visible if shown else ''
        tex = r'\mathbb{E}[S] = %s%d \times \underbrace{%s}_{\bar c} = %s, \qquad \bar c = \frac{%d}{%d}' % (
            lead,
            k,
            n2(avg),
            n2(mean),
            total_left,
            len(cards),
        )
        steps.append(step(label, words % (len(cards), n2(avg)), tex))
        return mean

    base = sum_step(
        full,
        'Without the event',
        'Each hidden card is equally likely to be any of the %d cards you cannot see, which average %s.',
    )
    mean_s = base
    if deck_key:
        mean_s = sum_step(
            pool,
            'The deck changes',
            'Now %s. ' % DECK_TEXT[deck_key] + 'The %d cards left average %s, so the expected sum moves.',
        )

    rule = ev.get('rule')
    params = ev.get('params', {})
    news = ev.get('news')
    probe = lambda fn: outcomes({'deck': ev.get('deck'), 'news': news, 'value': fn}, shown, k, seed)

    if rule == 'bonus':
        steps.append(
            step(
                'The bonus',
                'A fixed amount adds straight to fair value.',
                r'\mathbb{E}[\text{price}] = \mathbb{E}[S] + 10 = %s + 10 = %s'
                % (n2(mean_s), n2(mean_s + 10)),
            )
        )
    elif rule in CARD_RULES:
        f, rule_tex = CARD_RULES[rule]
        seen_f = sum(f(c) for c in shown)
        pool_f = sum(f(c) for c in pool)
        avg_f = pool_f / len(pool)
        lead = r'\underbrace{%d}_{\text{visible}} + ' % seen_f if shown else ''
        steps.append(
            step(
                'The new card values',
                'Each card now counts as f(c). By linearity of expectation every hidden card still averages '
                'over the cards it could be.',
                r'\begin{gathered} %s \\ \mathbb{E}[\text{price}] = %s%d \times \underbrace{%s}_{\bar f} %s %s, \qquad \bar f = \frac{%d}{%d} \end{gathered}'
                % (rule_tex, lead, k, n2(avg_f), eq, n2(seen_f + k * avg_f), pool_f, len(pool)),
            )
        )
    elif rule in ('double_high', 'drop_low', 'high_times'):
        pick = min if rule == 'drop_low' else max
        values = probe(lambda cs: pick(rank(c) for c in cs))
        e_x = statistics.fmean(values)
        dist = sorted(((v, values.count(v) / len(values)) for v in set(values)), reverse=(pick is max))
        terms = ' + '.join('%d(%s)' % (v, '%.3f' % p) for v, p in dist[:3]) + (
            r' + \dots' if len(dist) > 3 else ''
        )
        name = r'\max' if pick is max else r'\min'
        steps.append(
            step(
                'The %s card' % ('highest' if pick is max else 'lowest'),
                'Average the %s card over every possible hand: value times probability.'
                % ('highest' if pick is max else 'lowest'),
                r'\mathbb{E}[%s] = \sum_v v\,P(%s = v) = %s %s %s' % (name, name, terms, eq, n2(e_x)),
            )
        )
        if rule == 'double_high':
            tex = r'\mathbb{E}[\text{price}] = \mathbb{E}[S] + \mathbb{E}[\max] = %s + %s %s %s' % (
                n2(mean_s),
                n2(e_x),
                eq,
                n2(mean_s + e_x),
            )
        elif rule == 'drop_low':
            tex = r'\mathbb{E}[\text{price}] = \mathbb{E}[S] - \mathbb{E}[\min] = %s - %s %s %s' % (
                n2(mean_s),
                n2(e_x),
                eq,
                n2(mean_s - e_x),
            )
        else:
            tex = r'\mathbb{E}[\text{price}] = %d \times \mathbb{E}[\max] = %d \times %s %s %s' % (
                params['n'],
                params['n'],
                n2(e_x),
                eq,
                n2(params['n'] * e_x),
            )
        steps.append(step('With the event', 'Combine it with the expected sum.', tex))
    elif rule == 'pair_bonus':
        ranks_seen = [rank(c) for c in shown]
        if len(set(ranks_seen)) < len(ranks_seen):
            p_pair = 1.0
            tex = r'P(\text{pair}) = 1 \quad (\text{a pair is already showing})'
        elif not deck_key:
            m = len(set(ranks_seen))
            distinct = math.comb(13 - m, k) * 4**k
            hands = math.comb(len(pool), k)
            p_pair = 1 - distinct / hands
            tex = (
                r'P(\text{pair}) = 1 - \frac{\binom{%d}{%d}\,4^{%d}}{\binom{%d}{%d}} = 1 - \frac{%d}{%d} = %s'
                % (13 - m, k, k, len(pool), k, distinct, hands, '%.3f' % p_pair)
            )
        else:
            flags = probe(lambda cs: len({rank(c) for c in cs}) < len(cs))
            p_pair = sum(flags) / len(flags)
            tex = (
                r'P(\text{pair}) = \frac{\#\{\text{hands with a pair}\}}{\#\{\text{hands}\}} = \frac{%d}{%d} = %s'
                % (sum(flags), len(flags), '%.3f' % p_pair)
            )
        if p_pair == 1.0:
            words = 'You can already see two cards of the same rank, so the bonus is certain.'
        elif not deck_key:
            words = (
                'Easiest through the complement: count the hands where every rank is different '
                '(choose the unused ranks, then any of 4 suits each).'
            )
        else:
            words = 'With a changed deck, count directly: the share of possible hands that contain a pair.'
        steps.append(step('Chance of a pair', words, tex))
        steps.append(
            step(
                'With the event',
                'The bonus is paid only when there is a pair, so it adds 20 × P(pair).',
                r'\mathbb{E}[\text{price}] = \mathbb{E}[S] + 20\,P(\text{pair}) = %s + 20 \times %s %s %s'
                % (n2(mean_s), '%.3f' % p_pair, eq, n2(mean_s + 20 * p_pair)),
            )
        )
    elif rule in ('cap', 'collar'):
        sums = probe(total)
        cap = params['cap']
        over = statistics.fmean(max(x - cap, 0) for x in sums)
        p_over = sum(x > cap for x in sums) / len(sums)
        if rule == 'cap':
            steps.append(
                step(
                    'The cap',
                    'A cap takes away everything above it: P(S > %d) = %s, and the average excess is what you lose.'
                    % (cap, '%.3f' % p_over),
                    r'\mathbb{E}[\min(S, %d)] = \mathbb{E}[S] - \mathbb{E}[(S - %d)^+] = %s - %s %s %s'
                    % (cap, cap, n2(mean_s), n2(over), eq, n2(mean_s - over)),
                )
            )
        else:
            floor = params['floor']
            under = statistics.fmean(max(floor - x, 0) for x in sums)
            steps.append(
                step(
                    'The collar',
                    'The cap removes the excess above %d; the floor adds back the shortfall below %d.'
                    % (cap, floor),
                    r'\mathbb{E}[\text{price}] = \mathbb{E}[S] - \mathbb{E}[(S - %d)^+] + \mathbb{E}[(%d - S)^+] = %s - %s + %s %s %s'
                    % (cap, floor, n2(mean_s), n2(over), n2(under), eq, n2(mean_s - over + under)),
                )
            )
    elif rule == 'odd_half':
        sums = probe(total)
        odd = [x for x in sums if x % 2]
        p_odd = len(odd) / len(sums)
        cut = sum(x - x // 2 for x in odd) / len(sums)
        steps.append(
            step(
                'Halving odd totals',
                'An odd total S loses S − ⌊S/2⌋. Average that loss over every hand (it is zero for even totals).',
                r'P(S \text{ odd}) = %s, \qquad \mathbb{E}[\text{price}] = \mathbb{E}[S] - \mathbb{E}\big[\lceil S/2 \rceil \mathbf{1}_{S\ \text{odd}}\big] = %s - %s %s %s'
                % ('%.3f' % p_odd, n2(mean_s), n2(cut), eq, n2(mean_s - cut)),
            )
        )
    elif rule == 'face_news':
        faces = sum(1 for c in pool if is_face(c))
        n = len(pool)
        p_none = math.comb(n - faces, k) / math.comb(n, k)
        avg_all = sum(rank(c) for c in pool) / n
        rest = [c for c in pool if not is_face(c)]
        avg_rest = sum(rank(c) for c in rest) / len(rest)
        e_h, e_none = k * avg_all, k * avg_rest
        e_given = (e_h - p_none * e_none) / (1 - p_none)
        steps.append(
            step(
                'Chance of no face card',
                'First find how likely the news would have been false.',
                r'P(\text{no face}) = \frac{\binom{%d}{%d}}{\binom{%d}{%d}} = %s'
                % (n - faces, k, n, k, '%.3f' % p_none),
            )
        )
        steps.append(
            step(
                'Condition on the news',
                'Split the expected hidden total H by whether a face card appears, then solve for the case the news tells you.',
                r'\mathbb{E}[H \mid \text{face}] = \frac{\mathbb{E}[H] - P(\text{no face})\,\mathbb{E}[H \mid \text{no face}]}{1 - P(\text{no face})}'
                r' = \frac{%s - %s \times %s}{%s} = %s'
                % (n2(e_h), '%.3f' % p_none, n2(e_none), '%.3f' % (1 - p_none), n2(e_given)),
            )
        )
        steps.append(
            step(
                'With the event',
                'Add back the visible cards.',
                r'\mathbb{E}[\text{price}] = %s%s = %s'
                % ('%d + ' % visible if shown else '', n2(e_given), n2(visible + e_given)),
            )
        )
    elif rule == 'insider':
        steps.append(
            step(
                'With the event',
                'The news changes what one bot knows, not the price, so your fair value is unchanged. Watch its trades: '
                'they carry information about the hidden card it saw.',
                r'\mathbb{E}[\text{price}] = \mathbb{E}[S] = %s' % n2(mean_s),
            )
        )

    fair = public['mean']
    diff = fair - base
    if not ev:
        summary = 'No market event: fair value is the expected sum of the cards, %s.' % n2(fair)
    elif abs(diff) < 0.05:
        summary = 'The event barely moves fair value: %s without it, %s with it.' % (n2(base), n2(fair))
    else:
        summary = 'The event %s fair value by %s, from %s to %s.' % (
            'raises' if diff > 0 else 'lowers',
            n2(abs(diff)),
            n2(base),
            n2(fair),
        )
    return {'summary': summary, 'steps': steps, 'base': base, 'fair': fair}


RANK_FILTERS = {  # which values survive each deck change (one suit's worth), and copies of each value
    'even': (lambda v: v % 2 == 0, 4),
    'odd': (lambda v: v % 2 == 1, 4),
    'no_faces': (lambda v: not 11 <= v <= 13, 4),
    'high': (lambda v: v >= 8, 4),
    'low': (lambda v: v <= 7, 4),
    'red': (lambda v: True, 2),
}
CARD_SD = 3.74  # spread of one card's value (2 to 14)


def n1(x):
    return '%.1f' % x


def shortcut(ev, shown, k):
    """The quickest mental route to fair value: round numbers, one suit's values, no card counting.

    It ignores small corrections (the cards already showing are out of the deck) to stay fast; the
    page shows the result next to the exact value so the size of that shortcut is visible.
    """
    ev = ev or {}
    params = ev.get('params', {})
    deck_key = params.get('deck_key') or (ev.get('key') if ev.get('deck') and not ev.get('rule') else None)
    rule = ev.get('rule')
    keep, copies = RANK_FILTERS.get(deck_key, (lambda v: True, 4))
    values = [v for v in range(2, 15) if keep(v)]
    n = len(shown) + k
    visible = total(shown)

    # 1. What one hidden card is worth on average under the event.
    if rule in ('ace_low', 'blackjack'):
        f = CARD_RULES[rule][0]
        scored = [f(v - 2) for v in values]  # card v - 2 is the club of value v; suits score alike
        per_card = sum(scored) / len(scored)
        seen = sum(f(c) for c in shown)
        card_text = r'\bar f = \frac{%s}{%d} = \frac{%d}{%d} \approx %s' % (
            (
                ' + '.join(map(str, scored))
                if len(scored) <= 7
                else r'%d + \dots + %d' % (scored[0], scored[-1])
            ),
            len(scored),
            sum(scored),
            len(scored),
            n1(per_card),
        )
        card_words = 'Score one suit under the new values and average them.'
    elif rule == 'hearts_double':
        share = 0.5 if deck_key == 'red' else 0.25
        base = sum(values) / len(values)
        per_card = base * (1 + share)
        seen = visible + sum(rank(c) for c in shown if suit(c) == 2)
        card_text = r'\bar f = %s \times \left(1 + \tfrac{%s}{%s}\right) = %s' % (
            n1(base),
            '1' if share == 0.5 else '1',
            '2' if share == 0.5 else '4',
            n1(per_card),
        )
        card_words = (
            '%s of the deck is hearts, so a hidden card is worth its usual value plus that share.'
            % ('Half' if share == 0.5 else 'A quarter')
        )
    elif rule == 'red_minus_black':
        per_card = 0.0
        seen = sum(rank(c) if is_red(c) else -rank(c) for c in shown)
        card_text = r'\bar f = \tfrac12(+8) + \tfrac12(-8) = 0'
        card_words = 'Red and black are equally likely, so a hidden card is worth 0 on average.'
    else:
        per_card = sum(values) / len(values)
        seen = visible
        contiguous = values == list(range(values[0], values[-1] + 1))
        if contiguous:
            card_text = r'\bar c = \frac{%d + %d}{2} = %s' % (values[0], values[-1], n1(per_card))
            card_words = 'The values run evenly from %d to %d, so the average is the midpoint.' % (
                values[0],
                values[-1],
            )
        else:
            card_text = r'\bar c = \frac{%d}{%d} \approx %s' % (sum(values), len(values), n1(per_card))
            card_words = 'Average the %d values that can still be dealt.' % len(values)
    lead = '%d + ' % seen if shown else ''
    usual = seen + k * per_card
    sum_text = r'%s%d \times %s = %s' % (lead, k, n1(per_card), n1(usual))

    # 2. Apply the event's rule on top, still with round numbers.
    lo, hi = values[0], values[-1]
    if rule == 'bonus':
        estimate, words = usual + 10, 'Usual fair value plus the 10 bonus.'
        tex = r'%s,\qquad \text{fair} \approx %s + 10 = %s' % (card_text, n1(usual), n1(estimate))
    elif rule in ('double_high', 'drop_low', 'high_times'):
        high = rule != 'drop_low'
        count = len(values)
        # n cards spread evenly over the `count` possible values: the top one sits at position (V+1)n/(n+1).
        position = (count + 1) * n / (n + 1) if high else (count + 1) / (n + 1)
        guess = lo + (hi - lo) * (position - 1) / (count - 1)
        if shown:
            guess = (
                max(guess, max(rank(c) for c in shown)) if high else min(guess, min(rank(c) for c in shown))
            )
        name = r'\max' if high else r'\min'
        order = (
            r'\text{position} \approx \frac{(%d+1)%s}{%d+1} = %s \text{ of } %d \;\Rightarrow\; \mathbb{E}[%s] \approx %s'
            % (count, ('\\cdot %d' % n) if high else '', n, n1(position), count, name, n1(guess))
        )
        if rule == 'double_high':
            estimate = usual + guess
            tex = r'%s,\quad %s,\quad \text{fair} \approx %s + %s = %s' % (
                card_text,
                order,
                n1(usual),
                n1(guess),
                n1(estimate),
            )
        elif rule == 'drop_low':
            estimate = usual - guess
            tex = r'%s,\quad %s,\quad \text{fair} \approx %s - %s = %s' % (
                card_text,
                order,
                n1(usual),
                n1(guess),
                n1(estimate),
            )
        else:
            estimate = params['n'] * guess
            tex = r'%s,\qquad \text{fair} \approx %d \times %s = %s' % (
                order,
                params['n'],
                n1(guess),
                n1(estimate),
            )
        words = (
            'Spread the %d cards evenly over the %d possible values: the %s sits about %s of the way %s '
            '(and is never %s than the %s card you can see).'
            % (
                n,
                len(values),
                'highest' if high else 'lowest',
                'n/(n+1)' if high else '1/(n+1)',
                'up' if high else 'up from the bottom',
                'lower' if high else 'higher',
                'highest' if high else 'lowest',
            )
        )
    elif rule == 'pair_bonus':
        ranks_seen = [rank(c) for c in shown]
        if len(set(ranks_seen)) < len(ranks_seen):
            p, tex_p = 1.0, r'P(\text{pair}) = 1'
            words = 'A pair is already showing, so the 20 is certain.'
        else:
            deck = len(values) * copies
            factors = [(deck - copies * j, deck - j) for j in range(1, n)]
            p = 1 - math.prod(a / b for a, b in factors)
            product = r' \cdot '.join(r'\tfrac{%d}{%d}' % f for f in factors)
            tex_p = r'P(\text{pair}) = 1 - %s = %s' % (product, '%.2f' % p)
            words = (
                'Deal the cards one at a time: each new card must avoid the values already out, '
                'so card j has (%d − %dj) good cards out of (%d − j). One minus that product is the pair chance.'
                % (deck, copies, deck)
            )
        estimate = usual + 20 * p
        tex = r'%s,\qquad \text{fair} \approx %s + 20 \times %s = %s' % (
            tex_p,
            n1(usual),
            '%.2f' % p,
            n1(estimate),
        )
    elif rule in ('cap', 'collar'):
        sd = CARD_SD * math.sqrt(k)
        cap = params['cap']
        over = (
            max(0.0, 0.4 * sd + (usual - cap) / 2) if abs(cap - usual) < 1.5 * sd else max(0.0, usual - cap)
        )
        estimate = usual - over
        tex = (
            r'\sigma \approx 3.7\sqrt{%d} = %s,\quad \mathbb{E}[(S-%d)^+] \approx 0.4\sigma + \tfrac{%s - %d}{2} = %s'
            % (k, n1(sd), cap, n1(usual), cap, n1(over))
        )
        if rule == 'collar':
            floor = params['floor']
            under = (
                max(0.0, 0.4 * sd + (floor - usual) / 2)
                if abs(floor - usual) < 1.5 * sd
                else max(0.0, floor - usual)
            )
            estimate += under
            tex += r',\quad \mathbb{E}[(%d - S)^+] \approx %s' % (floor, n1(under))
        tex += r',\quad \text{fair} \approx %s' % n1(estimate)
        words = (
            'Treat the total as roughly normal with σ ≈ 3.7 per √card. Near the cap, the average excess you give up '
            'is about 0.4σ plus half of how far fair value sits above it.'
        )
    elif rule == 'odd_half':
        estimate = 0.75 * usual
        tex = (
            r'\text{fair} \approx \tfrac12\,\mathbb{E}[S] + \tfrac12\cdot\tfrac12\,\mathbb{E}[S] = \tfrac34 \times %s = %s'
            % (n1(usual), n1(estimate))
        )
        words = 'Half of totals are odd and keep only half their value: about three quarters of the usual fair value.'
    elif rule == 'face_news':
        p0 = (10 / 13) ** k
        e_given = (k * 8 - p0 * k * 6.8) / (1 - p0)
        estimate = visible + e_given
        tex = (
            r'P(\text{no face}) \approx \left(\tfrac{10}{13}\right)^{%d} = %s,\quad '
            r'\mathbb{E}[H\mid\text{face}] \approx \frac{%d(8) - %s \cdot %d(6.8)}{%s} = %s,\quad \text{fair} \approx %s'
            % (k, '%.2f' % p0, k, '%.2f' % p0, k, '%.2f' % (1 - p0), n1(e_given), n1(estimate))
        )
        words = (
            'A hidden card averages 8, or 6.8 if it is not a face card; 10 of 13 values are not faces. '
            'Back out the "at least one face" case from the overall average.'
        )
    else:
        estimate = usual
        tex = r'%s,\qquad \text{fair} \approx %s' % (card_text, sum_text)
        words = (
            card_words
            if rule in CARD_RULES or rule in ('hearts_double', 'red_minus_black') or deck_key
            else 'Every card from 2 to 14 is equally likely, so a hidden card averages the midpoint, 8.'
        )
        if rule == 'insider':
            words = (
                'The insider changes who knows what, not the price: price it like a normal round. ' + words
            )
    if rule in ('bonus',):
        words = card_words + ' ' + words
    # One idea per line, left-aligned, so long chains never run off the edge of the panel.
    lines = tex.replace(r',\qquad ', '\n').replace(r',\quad ', '\n').split('\n')
    tex = r'\begin{array}{l} ' + r' \\[4pt] '.join(r'\displaystyle ' + x for x in lines) + r' \end{array}'
    return {'words': words, 'tex': tex, 'estimate': estimate}


# ---- Bots ---------------------------------------------------------------------------------------

BOTS = [
    {
        'name': 'Player 2',
        'style': 'Cautious',
        'noise': 1.4,
        'threshold': 1.5,
        'aggression': 0.6,
        'width': 1,
        'reaction': (4.0, 7.0),
    },
    {
        'name': 'Player 3',
        'style': 'Sharp',
        'noise': 0.5,
        'threshold': 0.7,
        'aggression': 1.0,
        'width': 0,
        'reaction': (2.5, 5.0),
    },
    {
        'name': 'Player 4',
        'style': 'Aggressive',
        'noise': 1.1,
        'threshold': 0.4,
        'aggression': 1.7,
        'width': -1,
        'reaction': (1.5, 3.5),
    },
]
REACTION_SCALE = {'easy': 1.3, 'medium': 1.0, 'hard': 0.75}  # bots shout faster on harder tables


def bot_quote(bot, estimate, sd, min_spread, max_spread):
    spread = max(min_spread, min(max_spread, round(sd * 0.35) + bot['width']))
    bid = math.floor(estimate - spread / 2 + 0.5)
    return bid, bid + spread


def bot_order(bot, estimate, bid, ask, limits=None):
    """Buy, sell or pass against a quote, sized by how big the edge looks to this bot."""
    buy_edge, sell_edge = estimate - ask, bid - estimate
    edge = max(buy_edge, sell_edge)
    if edge <= bot['threshold']:
        return 'pass', 0
    side = 'buy' if buy_edge > sell_edge else 'sell'
    size = max(1, min(BOT_UNITS, round(edge * 2 * bot['aggression'])))
    if limits is not None:
        size = min(size, limits[side])
    return (side, size) if size > 0 else ('pass', 0)


# ---- The game -----------------------------------------------------------------------------------

PRESETS = {
    'easy': {
        'cards': 4,
        'shown': 2,
        'rounds': 6,
        'seconds': 30,
        'min_spread': 2,
        'max_spread': 6,
        'track': False,
    },
    'medium': {
        'cards': 4,
        'shown': 1,
        'rounds': 6,
        'seconds': 20,
        'min_spread': 2,
        'max_spread': 5,
        'track': False,
    },
    'hard': {
        'cards': 5,
        'shown': 1,
        'rounds': 8,
        'seconds': 15,
        'min_spread': 1,
        'max_spread': 4,
        'track': True,
    },
}
MODES = ('rotational', 'outcry', 'maker', 'taker')


def _int(cfg, key, lo, hi, default):
    value = cfg.get(key, default)
    label = key.replace('_', ' ').capitalize()
    if isinstance(value, bool):
        raise ValueError('%s must be a whole number.' % label)
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError('%s must be a whole number.' % label)
    if not lo <= value <= hi:
        raise ValueError('%s must be between %d and %d.' % (label, lo, hi))
    return value


def quote_text(q):
    return '%d at %d' % q


def points(x):
    """An expected amount: one decimal when small, whole points otherwise."""
    return '%+.1f' % x if abs(x) < 10 else '%+.0f' % x


class TradingGame:
    def __init__(self, cfg):
        self.difficulty = cfg.get('difficulty', 'medium')
        self.tier = cfg.get('tier', self.difficulty)
        if self.difficulty not in PRESETS and self.difficulty != 'custom':
            raise ValueError('Unknown difficulty.')
        if self.tier not in PRESETS:
            raise ValueError('Unknown event level.')
        self.mode = cfg.get('mode', 'rotational')
        if self.mode not in MODES:
            raise ValueError('Unknown market making mode.')
        base = PRESETS[self.tier]
        self.cards = _int(cfg, 'cards', 3, 6, base['cards'])
        self.shown = _int(cfg, 'shown', 0, self.cards - 1, min(base['shown'], self.cards - 1))
        self.rounds = _int(cfg, 'rounds', 2, 20, base['rounds'])
        self.seconds = _int(cfg, 'seconds', 0, 120, base['seconds'])  # 0 means no clock
        self.min_spread = _int(cfg, 'min_spread', 1, 20, base['min_spread'])
        self.max_spread = _int(
            cfg, 'max_spread', self.min_spread, 30, max(base['max_spread'], self.min_spread)
        )
        self.budget = _int(cfg, 'budget', 100, 100_000, 500)
        self.events = cfg.get('events', True) is not False
        self.check = cfg.get('check', True) is not False
        # Tracking your balance mentally: the balance is hidden and checked at the end.
        self.track = bool(cfg.get('track', base['track']))
        self.name = ' '.join(str(cfg.get('name') or '').split())[:20]
        self.id = secrets.token_urlsafe(20)
        self.rng = random.Random(secrets.token_hex(8))
        you = {'name': 'Player 1', 'you': True, 'style': None}
        self.players = [you] + [dict(b, you=False) for b in BOTS]
        self.scores = [self.budget] * 4
        self.history = []
        self.round = None
        self.final_check = None  # {'answer', 'actual', 'correct'} once the closing balance is reported
        self.awaiting_balance = False
        self.finished = False
        self.recorded = False
        self.next_round()

    # -- dealing

    def maker_index(self, number):
        if self.mode == 'maker':
            return 0
        if self.mode == 'taker':
            return 1 + (number - 1) % 3
        if self.mode == 'outcry':
            return None  # decided by the race to shout
        return (number - 1) % 4

    def next_round(self):
        number = len(self.history) + 1
        if number > self.rounds:
            self.round = None
            if self.track and self.final_check is None:
                self.awaiting_balance = True
            else:
                self.finished = True
            return
        ev = draw_event(self.rng, self.tier, self.cards) if self.events else None
        pool = hidden_pool(ev, [])
        for _ in range(500):
            hand = self.rng.sample(pool, self.cards)
            if not (ev and ev['news']) or ev['news'](tuple(hand[self.shown :])):
                break
        shown, hidden = hand[: self.shown], hand[self.shown :]
        seed = self.rng.randrange(1 << 30)
        public = fair_value(ev, shown, len(hidden), seed)
        insider, insider_card = None, None
        if ev and ev['insider']:
            insider = self.rng.randrange(1, 4)
            insider_card = self.rng.choice(hidden)
        estimates = {}
        for i in range(1, 4):
            info = fair_value(ev, shown, len(hidden), seed, insider_card) if i == insider else public
            noise = self.players[i]['noise'] * max(1.0, info['sd'] * 0.25)
            estimates[i] = {'mean': info['mean'] + self.rng.gauss(0, noise), 'sd': info['sd']}
        quotes = {
            i: bot_quote(self.players[i], est['mean'], est['sd'], self.min_spread, self.max_spread)
            for i, est in estimates.items()
        }
        scale = REACTION_SCALE.get(self.tier, 1.0)
        shouts = {i: scale * self.rng.uniform(*self.players[i]['reaction']) for i in range(1, 4)}
        maker = self.maker_index(number)
        self.round = {
            'number': number,
            'event': ev,
            'hand': hand,
            'shown': shown,
            'hidden': hidden,
            'public': public,
            'seed': seed,
            'insider': insider,
            'insider_card': insider_card,
            'maker': maker,
            'estimates': estimates,
            'bot_quotes': quotes,
            'shouts': shouts,
            'phase': 'event' if ev else None,
            'opened': None,
            'deadline': None,
            'quote': quotes[maker] if maker not in (None, 0) else None,
            'outcry': None,
            'orders': {},
            'result': None,
            'check': None,
        }
        if not ev:
            self.open_market()

    def open_market(self):
        """Start the round: an open-outcry race, or straight to decisions."""
        r = self.round
        r['opened'] = time.monotonic()
        if r['maker'] is None:
            r['phase'] = 'outcry'
            r['deadline'] = None
        else:
            self.open_decisions()

    def open_decisions(self):
        r = self.round
        r['phase'] = 'decide'
        r['deadline'] = time.monotonic() + self.seconds if self.seconds else None

    def begin(self):
        """The player has read the market event."""
        if self.round is None or self.round['phase'] != 'event':
            raise ValueError('There is no market event to dismiss.')
        self.open_market()

    def bots_win_outcry(self, your_time=None):
        """The fastest bot's shout makes the market; you trade against it."""
        r = self.round
        first = min(r['shouts'], key=r['shouts'].get)
        r['maker'] = first
        r['quote'] = r['bot_quotes'][first]
        r['outcry'] = {'winner': first, 'time': r['shouts'][first], 'your_time': your_time}
        self.open_decisions()

    def expired(self):
        r = self.round
        return (
            r
            and r['phase'] == 'decide'
            and r['deadline'] is not None
            and time.monotonic() > r['deadline'] + GRACE
        )

    def tick(self):
        """Advance on the clock: a bot wins the outcry, or a round whose clock ran out is settled."""
        r = self.round
        if r and r['phase'] == 'outcry' and time.monotonic() - r['opened'] >= min(r['shouts'].values()):
            self.bots_win_outcry()
        if self.expired():
            self.resolve(timed_out=True)

    def limits_for(self, i):
        r = self.round
        if r['quote'] is None:
            return {'buy': 0, 'sell': 0}
        return order_limits(
            self.scores[i], r['quote'][0], r['quote'][1], r['public']['max'], r['public']['min']
        )

    # -- your decisions

    def parse_quote(self, data):
        bid, ask = _int(data, 'bid', -500, 1000, None), _int(data, 'ask', -500, 1000, None)
        if not self.min_spread <= ask - bid <= self.max_spread:
            raise ValueError(
                'Your spread must be between %d and %d points (ask minus bid).'
                % (self.min_spread, self.max_spread)
            )
        return bid, ask

    def quote(self, data):
        r = self.round
        if r is not None and r['phase'] == 'outcry':
            quote = self.parse_quote(data)
            elapsed = time.monotonic() - r['opened']
            if elapsed < min(r['shouts'].values()):
                r['maker'], r['quote'] = 0, quote
                r['outcry'] = {'winner': 0, 'time': elapsed, 'your_time': elapsed}
                self.resolve()
            else:
                self.bots_win_outcry(your_time=elapsed)
            return
        self.tick()
        if r is None or r['phase'] != 'decide':
            raise ValueError('This round is not taking quotes.')
        if r['maker'] != 0:
            raise ValueError('You are not the market maker this round.')
        r['quote'] = self.parse_quote(data)
        self.resolve()

    def order(self, data):
        r = self.round
        self.tick()
        if r is None or r['phase'] != 'decide':
            raise ValueError('This round is not taking orders.')
        if r['maker'] == 0:
            raise ValueError('You are the market maker this round: post a quote instead.')
        side = data.get('side')
        if side not in ('buy', 'sell', 'pass'):
            raise ValueError('Choose buy, sell or pass.')
        size = 0
        if side != 'pass':
            limit = self.limits_for(0)[side]
            if limit < 1:
                raise ValueError('Your balance cannot cover that order. Pass, or take the other side.')
            size = _int(data, 'size', 1, limit, None)
        r['orders'][0] = (side, size)
        self.resolve()

    def resolve(self, timed_out=False):
        """Bots trade against the quote, cards are revealed and every player is paid."""
        r = self.round
        if r['maker'] != 0 and 'your_limits' not in r:
            r['your_limits'] = self.limits_for(0)  # what you could have traded, for the feedback
        if timed_out:
            if r['maker'] == 0:
                r['quote'] = None
            else:
                r['orders'][0] = ('pass', 0)
        quote = r['quote']
        if quote is not None:
            for i in range(1, 4):
                if i != r['maker']:
                    r['orders'][i] = bot_order(
                        self.players[i], r['estimates'][i]['mean'], *quote, self.limits_for(i)
                    )
        value = settle(r['event'], r['hand'])
        trades, pnl = [], [0, 0, 0, 0]
        for i, (side, size) in sorted(r['orders'].items()):
            if side == 'pass' or quote is None:
                continue
            price = quote[1] if side == 'buy' else quote[0]
            gain = (value - price) * size if side == 'buy' else (price - value) * size
            pnl[i] += gain
            pnl[r['maker']] -= gain
            trades.append({'player': i, 'side': side, 'size': size, 'price': price, 'pnl': gain})
        r['result'] = {'value': value, 'trades': trades, 'pnl': pnl, 'timed_out': timed_out}
        for i in range(1, 4):
            self.scores[i] += pnl[i]
        r['phase'] = 'check' if self.check else 'result'
        if not self.check:
            self.scores[0] += pnl[0]

    def answer(self, data):
        """The P&L check: exact answers only. A wrong answer forfeits gains and costs a penalty."""
        r = self.round
        if r is None or r['phase'] != 'check':
            raise ValueError('There is no P&L question right now.')
        given = self.parse_number(data)
        actual = r['result']['pnl'][0]
        correct = given == actual
        credited = actual if correct else min(actual, 0) - CHECK_PENALTY
        self.scores[0] += credited
        r['check'] = {'answer': given, 'actual': actual, 'correct': correct, 'credited': credited}
        r['phase'] = 'result'

    def report_balance(self, data):
        """Hard tables: report the closing balance you kept track of in your head."""
        if not self.awaiting_balance:
            raise ValueError('There is no balance to report right now.')
        given = self.parse_number(data)
        actual = self.scores[0]
        correct = given == actual
        if not correct:
            self.scores[0] -= CHECK_PENALTY
        self.final_check = {'answer': given, 'actual': actual, 'correct': correct}
        self.awaiting_balance = False
        self.finished = True

    @staticmethod
    def parse_number(data):
        raw = str(data.get('answer', '')).strip().replace(' ', '').replace(',', '').replace('−', '-')
        try:
            return int(raw)
        except ValueError:
            raise ValueError('Enter a whole number, with a minus sign for a loss.')

    def advance(self):
        r = self.round
        if r is None or r['phase'] != 'result':
            raise ValueError('Finish this round first.')
        self.history.append(self.summary_row(r))
        self.next_round()

    # -- reporting

    def summary_row(self, r):
        credited = r['check']['credited'] if r['check'] else r['result']['pnl'][0]
        return {
            'round': r['number'],
            'maker': r['maker'],
            'event': r['event']['text'] if r['event'] else None,
            'value': r['result']['value'],
            'fair': r['public']['mean'],
            'pnl': credited,
            'check': r['check']['correct'] if r['check'] else None,
        }

    def math(self, r):
        """The worked derivation of fair value, built once per round."""
        if 'math' not in r:
            r['math'] = explain(r['event'], r['shown'], len(r['hidden']), r['seed'], r['public'])
        return r['math']

    def why(self, r):
        """One sentence on where fair value came from; the full derivation is shown alongside."""
        return self.math(r)['summary']

    def feedback(self, r):
        """Concise coaching: what happened, the better play, and why. Extra notes only when they matter."""
        fair, sd = r['public']['mean'], r['public']['sd']
        res = r['result']
        pnl = res['pnl'][0]
        notes = []
        insider = r['insider']
        if r['maker'] == 0:
            return self.maker_feedback(r, fair, sd, res, pnl, notes, insider)
        return self.taker_feedback(r, fair, sd, res, pnl, notes, insider)

    def maker_feedback(self, r, fair, sd, res, pnl, notes, insider):
        if r['quote'] is None:
            spread = self.min_spread
            bid = math.floor(fair - spread / 2 + 0.5)
            return {
                'tone': 'bad',
                'title': 'No quote posted',
                'what': 'The clock ran out before you quoted, so nobody traded.',
                'better': 'Quote %s: start from fair value, then wrap the spread around it.'
                % quote_text((bid, bid + spread)),
                'why': self.why(r),
                'notes': notes,
            }
        bid, ask = r['quote']
        spread, mid = ask - bid, (bid + ask) / 2
        off = mid - fair
        ideal_bid = math.floor(fair - spread / 2 + 0.5)
        bought = sum(t['size'] for t in res['trades'] if t['side'] == 'buy')
        sold = sum(t['size'] for t in res['trades'] if t['side'] == 'sell')
        flow = []
        if bought:
            flow.append('bots bought %d from you' % bought)
        if sold:
            flow.append('bots sold %d to you' % sold)
        flow_text = ' and '.join(flow) if flow else 'nobody traded'
        if abs(off) <= spread / 2:
            what = 'You quoted %s around fair value %.1f; %s.' % (quote_text(r['quote']), fair, flow_text)
            if not bid <= res['value'] <= ask:
                notes.append(
                    'The cards settled at %d, outside your spread: that is variance (outcomes spread about ±%.1f), '
                    'not a pricing mistake.' % (res['value'], sd)
                )
            if insider:
                hits = [t for t in res['trades'] if t['player'] == insider]
                if hits and hits[0]['pnl'] > 0:
                    notes.append(
                        '%s had seen the %s and traded against you. When an informed player hits you, '
                        'widen or lean your next quote.'
                        % (self.players[insider]['name'], card_label(r['insider_card']))
                    )
            return {
                'tone': 'good',
                'title': 'Well-placed quote',
                'what': what,
                'better': None,
                'why': self.why(r),
                'notes': notes,
            }
        high = off > 0
        what = 'Your mid (%.1f) was %.1f points %s fair value %.1f, so %s.' % (
            mid,
            abs(off),
            'above' if high else 'below',
            fair,
            flow_text,
        )
        better = 'Quote %s, centred on fair value, keeping your %d-point spread.' % (
            quote_text((ideal_bid, ideal_bid + spread)),
            spread,
        )
        if pnl > 0:
            notes.append(
                'You still made %+d, but only because the cards fell your way; this quote loses on average.'
                % pnl
            )
        return {
            'tone': 'bad',
            'title': 'Quote too %s' % ('high' if high else 'low'),
            'what': what,
            'better': better,
            'why': self.why(r),
            'notes': notes,
        }

    def taker_feedback(self, r, fair, sd, res, pnl, notes, insider):
        bid, ask = r['quote']
        side, size = r['orders'].get(0, ('pass', 0))
        limits = r.get('your_limits') or {'buy': BOT_UNITS, 'sell': BOT_UNITS}
        edges = {'buy': fair - ask, 'sell': bid - fair}
        best = max(edges, key=edges.get) if max(edges.values()) > 0.25 else 'pass'
        price = {'buy': ask, 'sell': bid}

        def play(s, units):
            return '%s %d at %d (%+.1f a unit, about %s expected)' % (
                'buy' if s == 'buy' else 'sell',
                units,
                price[s],
                edges[s],
                points(edges[s] * units),
            )

        if insider and insider == r['maker']:
            notes.append(
                '%s, the market maker, had seen the %s: its quote leaned toward it.'
                % (self.players[insider]['name'], card_label(r['insider_card']))
            )
        if res['timed_out'] or side == 'pass':
            what = (
                'The clock ran out, so you passed.'
                if res['timed_out']
                else 'You passed on %s.' % quote_text(r['quote'])
            )
            if best == 'pass':
                return {
                    'tone': 'good' if not res['timed_out'] else 'tip',
                    'title': 'Good pass' if not res['timed_out'] else 'Out of time',
                    'what': what
                    + (' Passing was fine here: ' if res['timed_out'] else ' ')
                    + 'Fair value %.1f sat inside the quote, so there was no edge.' % fair,
                    'better': None,
                    'why': self.why(r),
                    'notes': notes,
                }
            if limits[best] < 1:
                return {
                    'tone': 'tip',
                    'title': 'No affordable trade',
                    'what': what
                    + ' The edge was on the %s side, but your balance could not cover that order.' % best,
                    'better': None,
                    'why': self.why(r),
                    'notes': notes,
                }
            units = max(1, min(limits[best], 5))
            return {
                'tone': 'bad',
                'title': 'Out of time' if res['timed_out'] else 'Missed edge',
                'what': what,
                'better': 'Better: ' + play(best, units) + '.',
                'why': self.why(r),
                'notes': notes,
            }
        did = '%s %d at %d' % ('Bought' if side == 'buy' else 'Sold', size, price[side])
        if side == best:
            what = '%s against fair value %.1f: %+.1f a unit, about %s expected.' % (
                did,
                fair,
                edges[side],
                points(edges[side] * size),
            )
            cap = limits[side]
            if edges[side] >= max(2.0, 0.25 * sd) and size <= 0.4 * cap and cap > size:
                notes.append(
                    'The edge was strong and you had room: up to %d units were allowed (about %s expected). '
                    'Size up when the edge is this clear.' % (cap, points(edges[side] * cap))
                )
            if pnl < 0:
                notes.append(
                    'The cards went against you (%+d), but the decision was right; judge the process, not one draw.'
                    % pnl
                )
            return {
                'tone': 'good',
                'title': 'Good trade',
                'what': what,
                'better': None,
                'why': self.why(r),
                'notes': notes,
            }
        if best == 'pass' and edges[side] > -0.5:
            return {
                'tone': 'tip',
                'title': 'Roughly fair trade',
                'what': '%s against fair value %.1f: %+.1f a unit, no real edge either way.'
                % (did, fair, edges[side]),
                'better': 'Pass when the quote surrounds fair value: a trade with no edge only adds risk.',
                'why': self.why(r),
                'notes': notes,
            }
        what = '%s, but fair value was %.1f: %+.1f a unit, about %s expected.' % (
            did,
            fair,
            edges[side],
            points(edges[side] * size),
        )
        better = (
            'Better: pass. Fair value %.1f sat inside %s.' % (fair, quote_text(r['quote']))
            if best == 'pass'
            else 'Better: ' + play(best, size) + '.'
        )
        if pnl > 0:
            notes.append(
                'You made %+d only because the cards fell your way; the same trade loses on average.' % pnl
            )
        return {
            'tone': 'bad',
            'title': 'Negative-edge trade',
            'what': what,
            'better': better,
            'why': self.why(r),
            'notes': notes,
        }

    def public(self):
        """What the browser may see. Hidden cards and bot reaction times stay hidden."""
        payload = {
            'id': self.id,
            'difficulty': self.difficulty,
            'tier': self.tier,
            'mode': self.mode,
            'rounds': self.rounds,
            'min_spread': self.min_spread,
            'max_spread': self.max_spread,
            'budget': self.budget,
            'seconds': self.seconds,
            'check': self.check,
            'track': self.track,
            'penalty': CHECK_PENALTY,
            'finished': self.finished,
            'awaiting_balance': self.awaiting_balance,
            'players': [
                {
                    'name': p['name'],
                    'you': p['you'],
                    'style': p['style'],
                    'score': None if (p['you'] and self.track and not self.finished) else s,
                }
                for p, s in zip(self.players, self.scores)
            ],
        }
        if self.finished:
            payload['summary'] = self.summary()
            return payload
        if self.awaiting_balance:
            payload['last_round'] = self.history[-1] if self.history else None
            return payload
        r = self.round
        settled = r['phase'] in ('check', 'result')
        now = time.monotonic()
        payload['round'] = {
            'number': r['number'],
            'phase': r['phase'],
            'maker': r['maker'],
            'event': {'text': r['event']['text']} if r['event'] else None,
            'quote': r['quote'],
            'elapsed': now - r['opened'] if r['phase'] == 'outcry' else None,
            'outcry': r['outcry'],
            'remaining': max(0, r['deadline'] - now) if r['deadline'] and r['phase'] == 'decide' else None,
            'cards': [
                (
                    {'label': card_label(c), 'red': is_red(c), 'up': True}
                    if settled or i < self.shown
                    else {'up': False}
                )
                for i, c in enumerate(r['hand'])
            ],
            'your_order': r['orders'].get(0),
        }
        if r['phase'] == 'decide' and r['maker'] != 0:
            payload['round']['limits'] = self.limits_for(0)
        if settled:
            res = r['result']
            payload['round']['result'] = {
                'value': res['value'],
                'fair': r['public']['mean'],
                'sd': r['public']['sd'],
                'hands': r['public']['hands'],
                'exact': r['public']['exact'],
                'trades': [dict(t, name=self.players[t['player']]['name']) for t in res['trades']],
                'pnl': res['pnl'] if r['phase'] == 'result' else None,
                'timed_out': res['timed_out'],
                'insider': (
                    {'name': self.players[r['insider']]['name'], 'card': card_label(r['insider_card'])}
                    if r['insider']
                    else None
                ),
            }
            if r['phase'] == 'result':
                payload['round']['feedback'] = self.feedback(r)
                math_ = self.math(r)
                payload['round']['math'] = {
                    'summary': math_['summary'],
                    'steps': math_['steps'],
                    'lesson': r['event']['lesson'] if r['event'] else None,
                    'shortcut': shortcut(r['event'], r['shown'], len(r['hidden'])),
                }
                payload['round']['check'] = r['check']
        return payload

    def summary(self):
        order = sorted(range(4), key=lambda i: -self.scores[i])
        return {
            'profit': self.scores[0] - self.budget,
            'score': self.scores[0],
            'budget': self.budget,
            'rounds': len(self.history),
            'place': order.index(0) + 1,
            'difficulty': self.difficulty,
            'mode': self.mode,
            'rankings': [
                {
                    'name': self.players[i]['name'],
                    'you': self.players[i]['you'],
                    'style': self.players[i]['style'],
                    'score': self.scores[i],
                    'profit': self.scores[i] - self.budget,
                }
                for i in order
            ],
            'history': self.history,
            'checks': sum(1 for h in self.history if h['check']),
            'checked': sum(1 for h in self.history if h['check'] is not None),
            'final_check': self.final_check,
        }

    def act(self, data):
        action = data.get('action')
        if self.finished:
            raise ValueError('This game has finished.')
        if action == 'begin':
            self.begin()
        elif action == 'quote':
            self.quote(data)
        elif action == 'order':
            self.order(data)
        elif action == 'answer':
            self.answer(data)
        elif action == 'balance':
            self.report_balance(data)
        elif action == 'next':
            self.advance()
        elif action != 'state':
            raise ValueError('Unknown action.')
        if self.round is not None:
            self.tick()
        if self.finished:
            self.record()
        return self.public()

    # -- the shared leaderboard (players who give a name, completed games only)

    def record(self):
        if self.recorded or not self.name:
            return
        self.recorded = True
        entries = load_leaderboard()
        entries.append(
            {
                'name': self.name,
                'profit': self.scores[0] - self.budget,
                'at': time.time(),
                'difficulty': self.difficulty,
            }
        )
        save_leaderboard(entries)


def load_leaderboard():
    try:
        data = json.loads(LEADERBOARD.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_leaderboard(entries):
    cutoff = time.time() - 30 * 86400
    entries = [e for e in entries if e.get('at', 0) >= cutoff][-5000:]
    try:
        LEADERBOARD.parent.mkdir(exist_ok=True)
        LEADERBOARD.write_text(json.dumps(entries), encoding='utf-8')
    except OSError:
        pass  # a read-only folder only costs the leaderboard


def leaderboard(limit=10):
    """Total profit per name over the last 30 days."""
    cutoff = time.time() - 30 * 86400
    totals = {}
    for e in load_leaderboard():
        if e.get('at', 0) >= cutoff and isinstance(e.get('name'), str):
            row = totals.setdefault(e['name'], {'name': e['name'], 'profit': 0, 'games': 0})
            row['profit'] += e.get('profit', 0)
            row['games'] += 1
    return sorted(totals.values(), key=lambda r: -r['profit'])[:limit]
