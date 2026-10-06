"""Sample spaces, question banks and exact probabilities.

Every board is a family of equally likely outcomes. Each outcome becomes a row of numeric
features, and a question ("event") is a comparison on one feature, so probabilities are exact
counts rather than simulations.
"""

import collections
import functools
import itertools
import math
from fractions import Fraction

SUITS = ['♣', '♦', '♥', '♠']
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97}
EFRON = {'A': (0, 0, 4, 4, 4, 4), 'B': (3, 3, 3, 3, 3, 3), 'C': (2, 2, 2, 2, 6, 6), 'D': (1, 1, 1, 5, 5, 5)}
TOPICS = ('dice', 'cards', 'coins', 'puzzles')


def card_label(card):
    rank = card % 13 + 1
    return {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(rank, str(rank)) + SUITS[card // 13]


def event(metric, op, target, label, tip=None):
    e = {'metric': metric, 'op': op, 'target': target, 'label': label}
    if tip:
        e['tip'] = tip
    return e


def longest_run(bits):
    best = run = 0
    for b in bits:
        run = run + 1 if b else 0
        best = max(best, run)
    return best


# ---- features: every outcome becomes a dict of numbers that events compare against


def number_features(values):
    s = sum(values)
    return {
        'sum': s,
        'product': math.prod(values),
        'max': max(values),
        'min': min(values),
        'odd': s % 2,
        'distinct': len(set(values)),
        'even_count': sum(v % 2 == 0 for v in values),
        'sum_prime': int(s in PRIMES),
    }


def dice2_features(o):
    a, b = o
    f = number_features(o)
    f.update(
        gap=abs(a - b),
        first_higher=int(a > b),
        divides=int(a % b == 0 or b % a == 0),
        square=int(math.isqrt(a * b) ** 2 == a * b),
    )
    return f


def dice3_features(o):
    lo, mid, hi = sorted(o)
    f = number_features(o)
    f.update(
        run=int(mid == lo + 1 and hi == mid + 1),
        rising=int(o[0] < o[1] < o[2]),
        sum_of_two=int(hi == lo + mid),
    )
    return f


def card_features(o):
    ranks = [c % 13 + 1 for c in o]
    f = number_features(ranks)
    red = sum(c // 13 in (1, 2) for c in o)
    f.update(
        red=red,
        hearts=sum(c // 13 == 2 for c in o),
        face=sum(r >= 11 for r in ranks),
        aces=ranks.count(1),
        same_suit=int(len({c // 13 for c in o}) == 1),
        suits=len({c // 13 for c in o}),
        same_colour=int(red in (0, len(o))),
    )
    if len(o) == 2:
        f.update(
            adjacent=int(abs(ranks[0] - ranks[1]) == 1),
            blackjack=int(sorted(ranks)[0] == 1 and sorted(ranks)[1] >= 10),
        )
    return f


def coin_features(bits):
    text = ''.join('H' if b else 'T' for b in bits)
    n = len(bits)
    return {
        'sum': sum(bits),
        'odd': sum(bits) % 2,
        'run': longest_run(bits),
        'no_hh': int('HH' not in text),
        'alternate': int(all(bits[i] != bits[i + 1] for i in range(n - 1))),
        'ends_match': int(bits[0] == bits[-1]),
        'hht': int('HHT' in text),
        'hth': int('HTH' in text),
        'first_more': int(sum(bits[: n // 2]) > sum(bits[n // 2 :])),
        'switches': sum(bits[i] != bits[i + 1] for i in range(n - 1)),
    }


def efron_features(o):
    v = {k: EFRON[k][i] for k, i in zip('ABCD', o)}
    f = {x + y: int(v[x] > v[y]) for x in 'ABCD' for y in 'ABCD' if x != y}
    f.update(
        A_all=int(all(v['A'] > v[y] for y in 'BCD')),
        beaten=sum(v['A'] > v[y] for y in 'BCD'),
        sum=sum(v.values()),
    )
    return f


def duel_features(o):
    a, b, c = o
    alice = max(a, b)
    return {
        'alice_win': int(alice > c),
        'tie': int(alice == c),
        'bob_win': int(alice < c),
        'both_beat': int(min(a, b) > c),
        'alice6': int(alice == 6),
        'margin': alice - c,
    }


def urn_features(o):
    seq = ''.join('R' if m < 5 else 'B' for m in o)
    return {
        'red': seq.count('R'),
        'all_same': int(len(set(seq)) == 1),
        'third_blue': int(seq[2] == 'B'),
        'ends_match': int(seq[0] == seq[2]),
        'last_only_blue': int(seq == 'RRB'),
        'alternate': int(seq in ('RBR', 'BRB')),
    }


def letter_features(p):
    seen, i, loop = set(), 0, 0
    while i not in seen:
        seen.add(i)
        i = p[i]
        loop += 1
    return {
        'fixed': sum(p[i] == i for i in range(len(p))),
        'first': int(p[0] == 0),
        'swap': int(p[0] == 1 and p[1] == 0),
        'cycle': int(loop == len(p)),
    }


def birthday_features(o):
    return {
        'distinct': len(set(o)),
        'share_first': int(o[0] in o[1:]),
        'quarters': int(len({m // 3 for m in o}) == 4),
        'half': int(len({m // 6 for m in o}) == 1),
        'dec': int(11 in o),
    }


def integer_features(o):
    n = o[0]
    return {
        'n': n,
        'div3': int(n % 3 == 0),
        'square': int(math.isqrt(n) ** 2 == n),
        'div35': int(n % 3 == 0 or n % 5 == 0),
        'odd_divisors': int(math.isqrt(n) ** 2 == n),
        'prime': int(n in PRIMES),
        'has7': int('7' in str(n)),
        'mod4': int(n % 4 == 1),
        'div6not4': int(n % 6 == 0 and n % 4 != 0),
        'digit_sum': sum(map(int, str(n))),
    }


# ---- question banks


def classic_events(kind, n, rows, base):
    """The threshold questions the trainer started with: sums, products, parity, matches.

    `base` is the level (1 easy, 2 medium, 3 hard) of the plainest questions for this board.
    """

    def graded(e, level):
        e['level'] = min(3, level)
        return e

    candidates = []
    if kind == 'coins':
        for k in range(1, n + 1):
            candidates.append(graded(event('sum', 'ge', k, 'At least %d heads' % k), base))
        for k in range(n + 1):
            candidates.append(graded(event('sum', 'eq', k, 'Exactly %d heads' % k), base))
        candidates.append(graded(event('odd', 'eq', 1, 'An odd number of heads'), base))
        return candidates
    top, noun = (6, 'dice') if kind == 'dice' else (13, 'ranks')
    every = 'Both' if n == 2 else 'All'
    # Sums of card ranks drawn without replacement are slow to count by hand.
    arithmetic = base if kind == 'dice' else 3
    for k in range(n + 1, n * top):
        candidates += [
            graded(event('sum', 'ge', k, 'Sum is at least %d' % k), arithmetic),
            graded(event('sum', 'le', k, 'Sum is at most %d' % k), arithmetic),
        ]
    for k in sorted({r['product'] for r in rows}):
        candidates.append(graded(event('product', 'gt', k, 'Product is greater than %d' % k), base + 1))
    candidates += [
        graded(event('odd', 'eq', 1, 'The sum is odd'), arithmetic),
        graded(event('distinct', 'eq', n, '%s %s are different' % (every, noun)), base),
        graded(
            event(
                'distinct', 'le', n - 1, ('The two %s match' if n == 2 else 'At least two %s match') % noun
            ),
            base,
        ),
        graded(event('even_count', 'eq', n, '%s %s are even' % (every, noun)), base),
    ]
    if kind == 'cards':
        candidates += [
            graded(event('red', 'eq', n, '%s cards are red' % every), 2),
            graded(event('red', 'eq', 1, 'Exactly one red card'), 2),
            graded(event('face', 'ge', 1, 'At least one face card (J, Q, K)'), 2),
            graded(event('aces', 'ge', 1, 'At least one ace'), 2),
            graded(event('same_suit', 'eq', 1, '%s cards have the same suit' % every), 2),
        ]
    else:
        candidates += [
            graded(event('max', 'eq', 6, 'At least one die shows a six'), base),
            graded(event('sum', 'eq', round(n * 3.5), 'Sum is exactly %d' % round(n * 3.5)), base),
        ]
    return candidates


def dice2_events(rows):
    return (
        classic_events('dice', 2, rows, 1)
        + [
            event(
                'gap',
                'ge',
                k,
                'The two dice differ by at least %d' % k,
                'A difference of exactly g happens in 2 × (6 − g) ordered ways. Add those up for g = %d to 5.'
                % k,
            )
            for k in (2, 3, 4)
        ]
        + [
            event(
                'first_higher',
                'eq',
                1,
                'The first die shows more than the second',
                'Symmetry: a tie has 6 of 36 outcomes, and the other 30 split evenly between "first higher" and "second higher": 15/36.',
            ),
            event(
                'sum_prime',
                'eq',
                1,
                'The sum is a prime number',
                'The prime sums are 2, 3, 5, 7 and 11, reached in 1 + 2 + 4 + 6 + 2 = 15 ways.',
            ),
            event(
                'divides',
                'eq',
                1,
                'One die divides the other exactly',
                'Fix the first die at 1, 2, …, 6: the second die works in 6, 4, 3, 3, 2, 4 ways (doubles count once). 22 of 36.',
            ),
            event(
                'square',
                'eq',
                1,
                'The product is a perfect square',
                'All 6 doubles work. The only other pairs are 1 and 4, in either order: 8 of 36.',
            ),
        ]
    )


def dice3_events(rows):
    return classic_events('dice', 3, rows, 2) + [
        event(
            'run',
            'eq',
            1,
            'The three dice form a run, like 3-4-5',
            'There are 4 runs (1-2-3 up to 4-5-6), each in 3! = 6 orders: 24 of 216.',
        ),
        event(
            'rising',
            'eq',
            1,
            'Each die shows more than the one before it',
            'Choose 3 different numbers, C(6, 3) = 20 ways. Only one of their 6 orders is increasing: 20 of 216.',
        ),
        event(
            'sum_of_two',
            'eq',
            1,
            'One die equals the sum of the other two',
            'Only the largest die can be the sum. List the sets {x, y, x + y} with x + y ≤ 6: three have x = y (3 orders each) and six do not (6 orders each): 45 of 216.',
        ),
        event(
            'sum_prime',
            'eq',
            1,
            'The sum is a prime number',
            'The possible prime sums are 3, 5, 7, 11, 13 and 17. Count the ways to make each.',
        ),
    ]


def cards2_events(rows):
    return classic_events('cards', 2, rows, 2) + [
        event(
            'same_colour',
            'eq',
            1,
            'Both cards are the same colour',
            'After the first card, 25 of the remaining 51 share its colour: 25/51, just under a half. Removing a card changes the odds.',
        ),
        event(
            'adjacent',
            'eq',
            1,
            'The ranks are neighbours, like 7 and 8 (ace low, no wrap)',
            '12 neighbouring rank pairs (A-2 up to Q-K), each with 4 × 4 suit choices: 12 × 16 = 192 hands.',
        ),
        event(
            'blackjack',
            'eq',
            1,
            'A blackjack: an ace together with a 10, J, Q or K',
            '4 aces × 16 ten-value cards = 64 hands out of 1,326.',
        ),
    ]


def cards3_events(rows):
    return classic_events('cards', 3, rows, 3) + [
        event(
            'distinct',
            'eq',
            2,
            'Exactly two cards share a rank (a pair, not three of a kind)',
            '13 ranks × C(4, 2) suit pairs × 48 cards of another rank = 3,744 hands.',
        ),
        event(
            'suits',
            'eq',
            3,
            'All three cards have different suits',
            'Choose the 3 suits, C(4, 3) = 4, then one of 13 cards in each: 4 × 13³ = 8,788 hands.',
        ),
        event(
            'max',
            'le',
            7,
            'Every card is a 7 or lower',
            '28 cards are 7 or lower (A to 7 in four suits): C(28, 3) / C(52, 3).',
        ),
    ]


def coins4_events(rows):
    return classic_events('coins', 4, rows, 1) + [
        event(
            'no_hh',
            'eq',
            1,
            'No two heads in a row',
            'Build left to right: valid sequences of length 1, 2, 3, 4 number 2, 3, 5, 8 (Fibonacci), so 8 of 16.',
        ),
        event(
            'alternate', 'eq', 1, 'Heads and tails strictly alternate', 'Only HTHT and THTH work: 2 of 16.'
        ),
        event(
            'ends_match',
            'eq',
            1,
            'The first and last flips match',
            'Once the first flip is known, only the last flip matters: 1/2. The middle flips are irrelevant.',
        ),
    ]


def coins8_events(rows):
    return [
        event(
            'run',
            'ge',
            3,
            'A run of at least 3 heads in a row',
            'Complement: sequences with no HHH follow a(n) = a(n−1) + a(n−2) + a(n−3), giving 149 of 256. Runs are more common than intuition says.',
        ),
        event(
            'run',
            'ge',
            4,
            'A run of at least 4 heads in a row',
            'Complement: sequences with no HHHH follow a(n) = a(n−1) + … + a(n−4), giving 208 of 256.',
        ),
        event(
            'hht',
            'eq',
            1,
            'The pattern H, H, T appears somewhere',
            'Avoiding HHT is hard: once HH appears, every later flip must be heads. HHT cannot overlap itself, so its copies never clump and it shows up in many sequences.',
        ),
        event(
            'hth',
            'eq',
            1,
            'The pattern H, T, H appears somewhere',
            'HTH overlaps itself (HTHTH holds two copies), so copies clump together and it appears in fewer sequences than HHT, even though both have a 1/8 chance at any single spot.',
        ),
        event(
            'no_hh',
            'eq',
            1,
            'No two heads in a row',
            'Fibonacci count: sequences of length n with no HH number F(n + 2), so 55 of 256.',
        ),
        event(
            'first_more',
            'eq',
            1,
            'More heads in the first four flips than in the last four',
            'Symmetry: the halves tie with probability Σ C(4, k)² / 256 = 70/256. The rest splits evenly: (256 − 70) / 2 = 93.',
        ),
        event(
            'switches',
            'ge',
            5,
            'The coin changes face at least 5 times',
            'Each of the 7 neighbouring pairs is a change with probability 1/2, independently: Binomial(7, 1/2) gives (21 + 7 + 1) / 128.',
        ),
        event(
            'sum',
            'eq',
            4,
            'Exactly 4 heads',
            'C(8, 4) = 70 of 256. It is the single most likely count, yet under 30%.',
        ),
        event(
            'sum', 'ge', 6, 'At least 6 heads', '(C(8, 6) + C(8, 7) + C(8, 8)) / 256 = (28 + 8 + 1) / 256.'
        ),
    ]


def efron_events(rows):
    return [
        event(
            'AB', 'eq', 1, 'Die A beats die B', 'B always shows 3, so A wins exactly when it shows a 4: 4/6.'
        ),
        event('BC', 'eq', 1, 'Die B beats die C', "B's 3 beats C's 2 and loses to C's 6: 4/6."),
        event(
            'CD',
            'eq',
            1,
            'Die C beats die D',
            "C's 6 always wins (2/6). C's 2 beats only D's 1 (4/6 × 1/2). Total 2/6 + 2/6 = 2/3.",
        ),
        event(
            'DA',
            'eq',
            1,
            'Die D beats die A',
            "D's 5 always wins (1/2). D's 1 beats only A's 0 (1/2 × 2/6). Total 2/3. So A beats B, B beats C, C beats D and D beats A: 'beats' is not transitive.",
        ),
        event('AC', 'eq', 1, 'Die A beats die C', 'A needs a 4 and C needs a 2: 4/6 × 4/6 = 4/9.'),
        event(
            'CA',
            'eq',
            1,
            'Die C beats die A',
            'No ties are possible, so this is the complement of A beating C: 1 − 4/9 = 5/9.',
        ),
        event('BD', 'eq', 1, 'Die B beats die D', "B's 3 beats D's 1 and loses to D's 5: 1/2."),
        event(
            'A_all',
            'eq',
            1,
            'Die A beats all three other dice',
            'A must show 4 (4/6), C must show 2 (4/6) and D must show 1 (1/2). B never matters once A shows 4. Total 2/9.',
        ),
    ]


CLUE6 = 'The clue leaves 11 equally likely ordered outcomes, not 6: (6,1) to (6,6) and (1,6) to (5,6). '


def clue6_events(rows):
    return [
        event(
            'min', 'eq', 6, 'Both dice are sixes', CLUE6 + 'Only one of them is a double six: 1/11, not 1/6.'
        ),
        event(
            'sum',
            'ge',
            10,
            'The sum is at least 10',
            CLUE6 + 'Sums of 10 or more: (6,4), (4,6), (6,5), (5,6), (6,6). That is 5/11.',
        ),
        event(
            'sum',
            'ge',
            9,
            'The sum is at least 9',
            CLUE6 + 'Add (6,3) and (3,6) to the five outcomes summing to 10 or more: 7/11.',
        ),
        event('sum', 'le', 8, 'The sum is at most 8', CLUE6 + 'Only (6,1), (6,2) and their reverses: 4/11.'),
        event(
            'odd',
            'eq',
            1,
            'The sum is odd',
            CLUE6 + 'The sum is odd when the other die is odd: (6,1), (6,3), (6,5) and their reverses, 6/11.',
        ),
        event('min', 'le', 2, 'The lower die shows 1 or 2', CLUE6 + '(6,1), (6,2), (1,6), (2,6): 4/11.'),
    ]


CLUE_RED = 'The clue removes the C(26, 2) = 325 all-black hands, leaving 1,001 equally likely hands. '


def cardsclue_events(rows):
    return [
        event(
            'red',
            'eq',
            2,
            'Both cards are red',
            CLUE_RED + 'C(26, 2) = 325 of them are all red: about 32%, not 50%.',
        ),
        event('red', 'eq', 1, 'Exactly one card is red', CLUE_RED + '26 × 26 = 676 of them are mixed.'),
        event('hearts', 'ge', 2, 'Both cards are hearts', CLUE_RED + 'C(13, 2) = 78 of them are two hearts.'),
        event(
            'hearts',
            'ge',
            1,
            'At least one card is a heart',
            CLUE_RED + 'Every hand with a heart is still possible: 1,326 − C(39, 2) = 585 of them.',
        ),
        event(
            'distinct',
            'le',
            1,
            'The two cards are a pair (same rank)',
            CLUE_RED + 'Each rank has C(4, 2) = 6 suit pairs, and only ♣♠ has no red card: 13 × 5 = 65.',
        ),
        event(
            'face',
            'ge',
            1,
            'At least one face card (J, Q, K)',
            CLUE_RED
            + 'Hands with a face card: 1,326 − C(40, 2) = 546. Remove the all-black ones, C(26, 2) − C(20, 2) = 135, leaving 411.',
        ),
    ]


def duel_events(rows):
    return [
        event(
            'alice_win',
            'eq',
            1,
            'Alice wins',
            "Alice's kept die is at most k with probability (k/6)². Average over Bob's roll c: Σ [1 − (c/6)²] / 6 = 125/216.",
        ),
        event(
            'tie',
            'eq',
            1,
            'It is a tie',
            "Alice's higher die equals c in 2c − 1 of her 36 pairs: Σ (2c − 1) / 216 = 36/216.",
        ),
        event(
            'bob_win',
            'eq',
            1,
            'Bob wins',
            "Bob needs both of Alice's dice below his: Σ ((c − 1)/6)² / 6 = 55/216.",
        ),
        event(
            'both_beat',
            'eq',
            1,
            "Both of Alice's dice beat Bob's die",
            'Σ ((6 − c)/6)² / 6 = 55/216. This mirrors "Bob wins" exactly: flip every die to 7 minus its value.',
        ),
        event(
            'alice6',
            'eq',
            1,
            'Alice keeps a six',
            'At least one of her two dice is a six: 1 − (5/6)² = 11/36.',
        ),
        event(
            'margin',
            'ge',
            3,
            'Alice wins by 3 or more',
            "For Bob's roll c = 1, 2, 3, Alice needs a higher die of at least c + 3: Σ [1 − ((c + 2)/6)²] / 6 = 58/216.",
        ),
    ]


def urn_events(rows):
    return [
        event(
            'red',
            'eq',
            2,
            'Exactly two red marbles',
            'Order does not matter here: C(5, 2) × C(3, 1) / C(8, 3) = 30/56.',
        ),
        event('red', 'eq', 3, 'All three marbles are red', '5/8 × 4/7 × 3/6 = 10/56.'),
        event('red', 'le', 2, 'At least one blue marble', 'Complement of all red: 1 − 10/56 = 46/56.'),
        event(
            'all_same',
            'eq',
            1,
            'All three marbles are the same colour',
            'All red (10/56) plus all blue (1/56): 11/56.',
        ),
        event(
            'third_blue',
            'eq',
            1,
            'The third marble drawn is blue',
            'Symmetry: the third draw is as likely to be any of the 8 marbles as the first draw is, so 3/8. Draws you have not seen change nothing.',
        ),
        event(
            'ends_match',
            'eq',
            1,
            'The first and third marbles are the same colour',
            'By symmetry, treat them as the first two draws: (5 × 4 + 3 × 2) / (8 × 7) = 26/56.',
        ),
        event(
            'last_only_blue',
            'eq',
            1,
            'Red, red, then blue: the only blue is the last one drawn',
            '5/8 × 4/7 × 3/6 = 60/336.',
        ),
        event(
            'alternate',
            'eq',
            1,
            'The colours alternate (red-blue-red or blue-red-blue)',
            'R-B-R: 5 × 3 × 4 = 60. B-R-B: 3 × 5 × 2 = 30. Total 90 of 336.',
        ),
    ]


def letter_events(rows):
    return [
        event(
            'fixed',
            'eq',
            0,
            'No letter lands in its own envelope',
            'Derangements: D(5) = 5! (1 − 1 + 1/2 − 1/6 + 1/24 − 1/120) = 44 of 120. The share stays close to 1/e ≈ 36.8% for any number of letters.',
        ),
        event(
            'fixed',
            'eq',
            1,
            'Exactly one letter lands in its own envelope',
            'Choose the lucky letter (5 ways), then derange the other four (D(4) = 9): 45 of 120.',
        ),
        event(
            'fixed',
            'ge',
            2,
            'At least two letters land in their own envelopes',
            'Complement of zero or one: 120 − 44 − 45 = 31.',
        ),
        event(
            'first',
            'eq',
            1,
            'Letter 1 lands in envelope 1',
            'Letter 1 is equally likely to land in any of the 5 envelopes: 1/5. The other letters do not matter.',
        ),
        event(
            'swap',
            'eq',
            1,
            "Letters 1 and 2 land in each other's envelopes",
            'Fix the swap, then arrange the other three freely: 3! = 6 of 120.',
        ),
        event(
            'cycle',
            'eq',
            1,
            'The mix-up is one single loop through all five letters',
            'Starting from letter 1, order the other four around the loop: 4! = 24 of 120.',
        ),
    ]


def birthday_events(rows):
    return [
        event(
            'distinct',
            'le',
            3,
            'At least two of the four share a birth month',
            'Complement: all different is 12 × 11 × 10 × 9 / 12⁴ ≈ 57.3%, so this is about 42.7%. Four people form 6 pairs, which is why it is so high.',
        ),
        event('distinct', 'eq', 4, 'All four birth months are different', '12 × 11 × 10 × 9 / 12⁴ ≈ 57.3%.'),
        event(
            'share_first',
            'eq',
            1,
            "Someone else shares Ana's birth month",
            'Only 3 pairs involve Ana: 1 − (11/12)³ ≈ 23%. Compare this with the any-pair version.',
        ),
        event(
            'quarters',
            'eq',
            1,
            'Everyone is born in a different quarter of the year',
            'Assign the 4 quarters to the 4 people (4! ways), then any of 3 months within each: 24 × 3⁴ / 12⁴.',
        ),
        event(
            'half', 'eq', 1, 'All four are born in the same half of the year', '2 halves × 6⁴ / 12⁴ = 1/8.'
        ),
        event('dec', 'eq', 1, 'At least one of them is born in December', '1 − (11/12)⁴ ≈ 29.4%.'),
    ]


def one_card_features(o):
    rank, suit = o[0] % 13 + 1, o[0] // 13
    return {
        'rank': rank,
        'red': int(suit in (1, 2)),
        'face': int(rank >= 11),
        'hearts': int(suit == 2),
        'ace_king': int(rank in (1, 13)),
        'high': int(rank >= 10),
        'heart_face': int(suit == 2 or rank >= 11),
    }


def one_card_events(rows):
    return [
        event('red', 'eq', 1, 'The card is red', 'Half the deck is red: 26 of 52.'),
        event('face', 'eq', 1, 'It is a face card (J, Q or K)', '3 face ranks × 4 suits = 12 of 52.'),
        event('hearts', 'eq', 1, 'It is a heart', '13 of the 52 cards: 1/4.'),
        event(
            'rank', 'le', 5, 'Its rank is 5 or lower (an ace counts as 1)', '5 ranks × 4 suits = 20 of 52.'
        ),
        event('ace_king', 'eq', 1, 'It is an ace or a king', '2 ranks × 4 suits = 8 of 52.'),
        event('high', 'eq', 1, 'It is a 10, J, Q or K', '4 ranks × 4 suits = 16 of 52.'),
        event(
            'heart_face',
            'eq',
            1,
            'It is a heart or a face card',
            'Inclusion–exclusion: 13 hearts + 12 face cards − 3 heart face cards = 22 of 52.',
        ),
    ]


def integer_events(rows):
    return [
        event('div3', 'eq', 1, 'It is divisible by 3', '3, 6, 9, …, 99: 33 numbers.'),
        event('square', 'eq', 1, 'It is a perfect square', '1, 4, 9, …, 100: 10 numbers.'),
        event('n', 'le', 30, 'It is 30 or less', '30 of the 100 numbers.'),
        event(
            'div35',
            'eq',
            1,
            'It is divisible by 3 or by 5',
            'Inclusion–exclusion: 33 + 20 − 6 (multiples of 15) = 47.',
        ),
        event(
            'odd_divisors',
            'eq',
            1,
            'It has an odd number of divisors',
            'Divisors pair up as d and n/d, except when n is a perfect square. So this means the 10 squares.',
        ),
        event(
            'prime',
            'eq',
            1,
            'It is a prime number',
            'There are 25 primes below 100, a number worth memorising.',
        ),
        event(
            'has7',
            'eq',
            1,
            'It contains the digit 7',
            'Ones digit 7: 10 numbers. Tens digit 7: 10 numbers. 77 is counted twice: 19.',
        ),
        event('mod4', 'eq', 1, 'It leaves remainder 1 when divided by 4', '1, 5, 9, …, 97: 25 numbers.'),
        event(
            'div6not4',
            'eq',
            1,
            'It is divisible by 6 but not by 4',
            '16 multiples of 6, minus the 8 multiples of 12: 8.',
        ),
        event(
            'digit_sum',
            'ge',
            10,
            'Its digits add up to 10 or more',
            'With tens digit t, the ones digit must be at least 10 − t: 1 + 2 + … + 9 = 45 numbers.',
        ),
    ]


# ---- reveal tokens and one-line outcome notes


def pips(o):
    return list(o), [False] * len(o)


def card_tokens(o):
    return [card_label(c) for c in o], [c // 13 in (1, 2) for c in o]


def coin_tokens(o):
    return ['H' if b else 'T' for b in o], [False] * len(o)


FAMILIES = {
    'dice2': dict(
        grades=(2, {'One die divides the other exactly': 3}),
        title='Two dice',
        rules='Two independent fair six-sided dice.',
        kind='dice',
        n=2,
        topic='dice',
        method='Count ordered dice outcomes: each of the 6^2 = 36 outcomes is equally likely.',
        outcomes=lambda: itertools.product(range(1, 7), repeat=2),
        features=dice2_features,
        events=dice2_events,
        tokens=pips,
        style='dice',
        hist=('sum', 'the sum'),
        classic=True,
        note=lambda o, f: 'Sum %d · Product %d' % (f['sum'], f['product']),
    ),
    'dice3': dict(
        grades=(3, {'The three dice form a run, like 3-4-5': 2}),
        title='Three dice',
        rules='Three independent fair six-sided dice.',
        kind='dice',
        n=3,
        topic='dice',
        method='Count ordered dice outcomes: each of the 6^3 = 216 outcomes is equally likely.',
        outcomes=lambda: itertools.product(range(1, 7), repeat=3),
        features=dice3_features,
        events=dice3_events,
        tokens=pips,
        style='dice',
        hist=('sum', 'the sum'),
        classic=True,
        note=lambda o, f: 'Sum %d · Product %d' % (f['sum'], f['product']),
    ),
    'clue6': dict(
        grades=(3, {}),
        title='Two dice and a clue',
        kind='dice',
        n=2,
        topic='dice',
        rules="Two fair dice are rolled out of sight. Someone who saw them says truthfully: “at least one of them is a six.”",
        method='The clue removes every outcome without a six: 11 of the 36 ordered outcomes remain, all equally likely.',
        outcomes=lambda: (o for o in itertools.product(range(1, 7), repeat=2) if 6 in o),
        features=number_features,
        events=clue6_events,
        tokens=pips,
        style='dice',
        hist=('sum', 'the sum'),
        note=lambda o, f: 'Sum %d. The clue was true: at least one six.' % f['sum'],
    ),
    'duel': dict(
        grades=(3, {'Alice keeps a six': 2}),
        title='Dice duel',
        kind='dice',
        n=3,
        topic='dice',
        slots=['A', 'A', 'B'],
        rules="Alice rolls two fair dice and keeps the higher one. Bob rolls one fair die. The higher number wins; equal numbers are a tie. The first two dice shown are Alice's.",
        method='Count ordered dice outcomes: each of the 6^3 = 216 outcomes is equally likely.',
        outcomes=lambda: itertools.product(range(1, 7), repeat=3),
        features=duel_features,
        events=duel_events,
        tokens=pips,
        style='dice',
        hist=('margin', "Alice's kept die minus Bob's die"),
        note=lambda o, f: 'Alice keeps %d · Bob rolls %d' % (max(o[:2]), o[2]),
    ),
    'efron': dict(
        grades=(3, {}),
        title="Efron's dice",
        kind='dice',
        n=4,
        topic='dice',
        slots=['A', 'B', 'C', 'D'],
        rules='Four fair dice with unusual faces are rolled once each. A: 0 0 4 4 4 4. B: 3 3 3 3 3 3. C: 2 2 2 2 6 6. D: 1 1 1 5 5 5.',
        method='Count face combinations: each of the 6^4 = 1,296 is equally likely. Repeated numbers are still different faces.',
        outcomes=lambda: itertools.product(range(6), repeat=4),
        features=efron_features,
        events=efron_events,
        tokens=lambda o: (['%s%d' % (k, EFRON[k][i]) for k, i in zip('ABCD', o)], [False] * 4),
        style='text',
        hist=('beaten', 'dice beaten by A'),
        note=lambda o, f: 'Die A beat %d of the other three.' % f['beaten'],
    ),
    'cards2': dict(
        grades=(2, {'The ranks are neighbours, like 7 and 8 (ace low, no wrap)': 3}),
        title='Two cards',
        kind='cards',
        n=2,
        topic='cards',
        rules='Two cards drawn without replacement from a fresh 52-card deck. A=1, J=11, Q=12, K=13.',
        method='Count physical-card combinations: C(52, 2) = 1,326 equally likely hands. Ranks are NOT independent because cards are drawn without replacement.',
        outcomes=lambda: itertools.combinations(range(52), 2),
        features=card_features,
        events=cards2_events,
        tokens=card_tokens,
        style='text',
        hist=('sum', 'the sum of ranks'),
        classic=True,
        note=lambda o, f: 'Sum %d · Product %d' % (f['sum'], f['product']),
    ),
    'cards3': dict(
        grades=(3, {'Every card is a 7 or lower': 2}),
        title='Three cards',
        kind='cards',
        n=3,
        topic='cards',
        rules='Three cards drawn without replacement from a fresh 52-card deck. A=1, J=11, Q=12, K=13.',
        method='Count physical-card combinations: C(52, 3) = 22,100 equally likely hands. Ranks are NOT independent because cards are drawn without replacement.',
        outcomes=lambda: itertools.combinations(range(52), 3),
        features=card_features,
        events=cards3_events,
        tokens=card_tokens,
        style='text',
        hist=('sum', 'the sum of ranks'),
        classic=True,
        note=lambda o, f: 'Sum %d · Product %d' % (f['sum'], f['product']),
    ),
    'cardsclue': dict(
        grades=(3, {}),
        title='Two cards and a clue',
        kind='cards',
        n=2,
        topic='cards',
        rules="Two cards are dealt face down from a fresh 52-card deck. The dealer looks at both and says truthfully: “at least one of them is red.” A=1, J=11, Q=12, K=13.",
        method='The clue removes the 325 all-black hands: 1,326 − 325 = 1,001 equally likely hands remain.',
        outcomes=lambda: (
            o for o in itertools.combinations(range(52), 2) if any(c // 13 in (1, 2) for c in o)
        ),
        features=card_features,
        events=cardsclue_events,
        tokens=card_tokens,
        style='text',
        hist=('sum', 'the sum of ranks'),
        note=lambda o, f: '%d red card%s.' % (f['red'], '' if f['red'] == 1 else 's'),
    ),
    'coins': dict(
        grades=(1, {'No two heads in a row': 2}),
        title='Four coins',
        rules='Four independent fair coin flips. Heads=1, tails=0.',
        kind='coins',
        n=4,
        topic='coins',
        method='Count ordered flips: each of the 2^4 = 16 sequences is equally likely.',
        outcomes=lambda: itertools.product((0, 1), repeat=4),
        features=coin_features,
        events=coins4_events,
        tokens=coin_tokens,
        style='text',
        hist=('sum', 'heads'),
        classic=True,
        note=lambda o, f: '%d head%s' % (f['sum'], '' if f['sum'] == 1 else 's'),
    ),
    'coins8': dict(
        grades=(
            2,
            {
                'A run of at least 3 heads in a row': 3,
                'A run of at least 4 heads in a row': 3,
                'The pattern H, H, T appears somewhere': 3,
                'The pattern H, T, H appears somewhere': 3,
            },
        ),
        title='Eight coin flips',
        rules='Eight independent fair coin flips, in order. Patterns are read left to right.',
        kind='coins',
        n=8,
        topic='coins',
        method='Count ordered flips: each of the 2^8 = 256 sequences is equally likely.',
        outcomes=lambda: itertools.product((0, 1), repeat=8),
        features=coin_features,
        events=coins8_events,
        tokens=coin_tokens,
        style='text',
        hist=('run', 'the longest run of heads'),
        note=lambda o, f: '%d heads · longest run of heads %d' % (f['sum'], f['run']),
    ),
    'urn': dict(
        grades=(
            2,
            {'The third marble drawn is blue': 3, 'The first and third marbles are the same colour': 3},
        ),
        title='The marble bag',
        kind='urn',
        n=3,
        topic='puzzles',
        rules='A bag holds 5 red and 3 blue marbles. Three are drawn one at a time, without replacement, and their order is recorded.',
        method='Count ordered draws of individual marbles: 8 × 7 × 6 = 336 equally likely sequences.',
        outcomes=lambda: itertools.permutations(range(8), 3),
        features=urn_features,
        events=urn_events,
        tokens=lambda o: (['R' if m < 5 else 'B' for m in o], [m < 5 for m in o]),
        style='text',
        hist=('red', 'red marbles drawn'),
        note=lambda o, f: 'Drawn in order: ' + ', '.join('red' if m < 5 else 'blue' for m in o),
    ),
    'letters': dict(
        grades=(3, {'Letter 1 lands in envelope 1': 2, "Letters 1 and 2 land in each other's envelopes": 2}),
        title='Letters and envelopes',
        kind='letters',
        n=5,
        topic='puzzles',
        slots=['1', '2', '3', '4', '5'],
        rules='Five letters are put into their five addressed envelopes completely at random, one letter per envelope.',
        method='Count arrangements: each of the 5! = 120 ways to stuff the envelopes is equally likely.',
        outcomes=lambda: itertools.permutations(range(5)),
        features=letter_features,
        events=letter_events,
        tokens=lambda o: (['%d→%d' % (i + 1, p + 1) for i, p in enumerate(o)], [False] * 5),
        style='text',
        hist=('fixed', 'letters in the right envelope'),
        note=lambda o, f: '%d letter%s in the right envelope (tokens read letter→envelope).'
        % (f['fixed'], '' if f['fixed'] == 1 else 's'),
    ),
    'birthday': dict(
        grades=(2, {'Everyone is born in a different quarter of the year': 3}),
        title='Birth months',
        kind='people',
        n=4,
        topic='puzzles',
        slots=['A', 'B', 'C', 'D'],
        rules='Four people, Ana, Ben, Cai and Dev, each have a birth month chosen uniformly at random and independently. Ignore month lengths.',
        method='Count month assignments: each of the 12^4 = 20,736 is equally likely.',
        outcomes=lambda: itertools.product(range(12), repeat=4),
        features=birthday_features,
        events=birthday_events,
        tokens=lambda o: ([MONTHS[m] for m in o], [False] * 4),
        style='text',
        hist=('distinct', 'different months'),
        note=lambda o, f: 'Ana, Ben, Cai, Dev: %d different month%s.'
        % (f['distinct'], '' if f['distinct'] == 1 else 's'),
    ),
    'card1': dict(
        grades=(1, {'It is a heart or a face card': 2}),
        title='One card',
        kind='cards',
        n=1,
        topic='cards',
        rules='One card drawn from a fresh, shuffled 52-card deck. A=1, J=11, Q=12, K=13.',
        method='Each of the 52 cards is equally likely, so count the cards that qualify.',
        outcomes=lambda: ((c,) for c in range(52)),
        features=one_card_features,
        events=one_card_events,
        tokens=card_tokens,
        style='text',
        hist=('rank', 'the rank'),
        note=lambda o, f: 'The card was %s.' % card_label(o[0]),
    ),
    'integer': dict(
        grades=(
            2,
            {
                'It is divisible by 3': 1,
                'It is a perfect square': 1,
                'It is 30 or less': 1,
                'It leaves remainder 1 when divided by 4': 1,
                'It has an odd number of divisors': 3,
            },
        ),
        title='A number from 1 to 100',
        kind='number',
        n=1,
        topic='puzzles',
        rules='A whole number is picked uniformly at random from 1 to 100.',
        method='Each of the 100 numbers is equally likely, so count the numbers that qualify.',
        outcomes=lambda: ((k,) for k in range(1, 101)),
        features=integer_features,
        events=integer_events,
        tokens=lambda o: ([str(o[0])], [False]),
        style='text',
        hist=('digit_sum', 'the digit sum'),
        note=lambda o, f: 'The number was %d.' % o[0],
    ),
}


@functools.lru_cache(maxsize=None)
def sample_space(family):
    spec = FAMILIES[family]
    outcomes = tuple(spec['outcomes']())
    rows = tuple(spec['features'](outcome) for outcome in outcomes)
    return outcomes, rows


def wins(event, row):
    value, target = row[event['metric']], event['target']
    return {'ge': value >= target, 'le': value <= target, 'eq': value == target, 'gt': value > target}[
        event['op']
    ]


@functools.lru_cache(maxsize=None)
def event_bank(family):
    _, rows = sample_space(family)
    default, overrides = FAMILIES[family]['grades']
    candidates = [
        dict(e, level=overrides.get(e['label'], e.get('level', default)))
        for e in FAMILIES[family]['events'](rows)
    ]
    # Build metric histograms once instead of re-enumerating for every threshold.
    hist = {key: collections.Counter(r[key] for r in rows) for key in rows[0]}
    result = []
    for e in candidates:
        count = sum(freq for value, freq in hist[e['metric']].items() if wins(e, {e['metric']: value}))
        if 0.045 <= count / len(rows) <= 0.92:
            result.append(dict(e, count=count, total=len(rows), p=count / len(rows)))
    return tuple(result)


def classic_tip(spec, e):
    """Shortcuts for the auto-generated threshold questions, which carry no tip of their own."""
    kind, n = spec['kind'], spec['n']
    if e['metric'] == 'sum' and e['op'] == 'ge' and kind != 'coins':
        return 'Complement shortcut: P(sum ≥ %d) = 1 − P(sum ≤ %d).' % (e['target'], e['target'] - 1)
    if e['metric'] == 'product' and kind == 'dice' and n == 2:
        counts = [sum(a * b > e['target'] for b in range(1, 7)) for a in range(1, 7)]
        return (
            'Fix die 1 at 1, 2, …, 6. The allowed counts for die 2 are %s; add them and divide by 36.'
            % ', '.join(map(str, counts))
        )
    if e['metric'] == 'face':
        return 'Complement: 1 − C(40, %d) / C(52, %d), since 40 cards are not J, Q or K.' % (n, n)
    if e['metric'] == 'aces':
        return 'Complement: 1 − C(48, %d) / C(52, %d), since 48 cards are not aces.' % (n, n)
    if e['metric'] == 'same_suit':
        return 'Choose the suit, then the hand: 4 × C(13, %d) / C(52, %d).' % (n, n)
    if e['metric'] == 'red':
        return 'Hypergeometric count: C(26, %d) × C(26, %d) / C(52, %d).' % (e['target'], n - e['target'], n)
    if kind == 'coins' and e['metric'] == 'sum':
        if e['op'] == 'eq':
            return 'Choose the positions of the heads: C(%d, %d) / 2^%d.' % (n, e['target'], n)
        return 'Add the binomial counts C(%d, k) for k = %d to %d, then divide by 2^%d.' % (
            n,
            e['target'],
            n,
            n,
        )
    if e['metric'] == 'max' and kind == 'dice':
        return 'Complement: 1 − (5/6)^%d, the probability that not all dice avoid six.' % n
    if e['metric'] == 'sum' and e['op'] in ('le', 'eq'):
        return (
            'List the ways to reach each total up to %d; small totals have few ways, so count them directly.'
            % e['target']
        )
    if e['metric'] == 'distinct':
        if kind == 'dice':
            different = 'all different = %s / 6^%d' % (' × '.join(str(6 - i) for i in range(n)), n)
        else:
            different = 'all different ranks = C(13, %d) × 4^%d / C(52, %d)' % (n, n, n)
        return (
            ('Count directly: ' if e['op'] == 'eq' and e['target'] == n else 'Use the complement of ')
            + different
            + '.'
        )
    if e['metric'] == 'odd':
        if kind == 'dice':
            return 'Each die is odd or even with probability 1/2, so the sum is odd exactly half the time.'
        return (
            'The sum is odd when an odd number of cards have odd ranks. 28 cards are odd (A, 3, 5, 7, 9, J, K) '
            'and 24 are even: count the mixes with C(28, k) × C(24, %d − k).' % n
        )
    if e['metric'] == 'even_count':
        if kind == 'dice':
            return 'Each die is even with probability 1/2, independently: (1/2)^%d.' % n
        return '24 cards have even ranks (2, 4, 6, 8, 10, Q): C(24, %d) / C(52, %d).' % (n, n)
    if e['metric'] == 'product':
        return (
            'Products grow fast: list the few combinations that stay at or below %d, then take the complement.'
            % e['target']
        )
    return None


NUDGES = (  # (words in the worked tip, first hint): checked in order, first match wins
    (
        ('clue',),
        'The clue changes the sample space. List the outcomes that are still possible before you count anything.',
    ),
    (
        ('symmetry', 'mirror', 'equally likely to land', 'as likely to be any'),
        'Look for symmetry: is every position or player really alike here?',
    ),
    (('complement', '1 −'), 'Try the complement: it is often easier to count the outcomes you do NOT want.'),
    (
        ('fibonacci', 'a(n)', 'overlap'),
        'Build the sequences left to right and look for a pattern or recursion in the counts.',
    ),
    (
        ('inclusion', ' − 3 heart', 'counted twice'),
        'Count each condition on its own, then fix the overlap you counted twice.',
    ),
    (
        ('derange',),
        'Think about which letters are allowed where, and count the arrangements where none is right.',
    ),
    (
        ('binomial', 'c(8', 'c(4', 'choose the positions'),
        'Choose which positions hold the heads: the counts come from binomial coefficients.',
    ),
    (
        ('c(52', 'c(13', 'c(26', 'c(28', 'c(40', 'c(48', '× 16', 'suit'),
        'Count hands of cards (order does not matter): favourable hands over C(52, n).',
    ),
)


def nudge(family, e):
    """A first hint that points at a method without giving away any numbers."""
    tip = (e.get('tip') or classic_tip(FAMILIES[family], e) or '').lower()
    for words, hint in NUDGES:
        if any(w in tip for w in words) or (words == ('clue',) and family in ('clue6', 'cardsclue')):
            return hint
    return {
        'dice': 'Count ordered outcomes: every cell of the 6^n grid is equally likely.',
        'coins': 'Every sequence of heads and tails is equally likely: count the ones that qualify.',
        'cards': 'Count hands of cards (order does not matter): favourable hands over C(52, n).',
    }.get(
        FAMILIES[family]['kind'], 'Count the equally likely outcomes that qualify, then divide by the total.'
    )


def explanation(family, e):
    spec = FAMILIES[family]
    fraction = str(Fraction(e['count'], e['total']))
    tip = (
        e.get('tip')
        or (classic_tip(spec, e) if spec.get('classic') else None)
        or 'Count outcomes meeting the condition, then divide by the full sample space.'
    )
    return {
        'nudge': nudge(family, e),
        'method': spec['method'],
        'counting': '%s favourable / %s total = %s = %.2f%%.'
        % (format(e['count'], ','), format(e['total'], ','), fraction, 100 * e['p']),
        'tip': tip,
    }


def analyse(e):
    p, b = e['p'], e['odds']
    edge = p * (b + 1) - 1
    return dict(
        p=p,
        fair_odds=(1 - p) / p,
        breakeven=1 / (1 + b),
        ev=edge,
        kelly=max(0, edge / b),
        fraction=str(Fraction(e['count'], e['total'])),
    )
