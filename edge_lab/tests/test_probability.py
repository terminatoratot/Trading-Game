"""Exact probabilities, sample spaces and question banks."""

import math
import random
import unittest
from fractions import Fraction

from edge_lab.probability import FAMILIES, analyse, event, event_bank, sample_space, wins


class ProbabilityTests(unittest.TestCase):
    def test_sample_spaces(self):
        for f, size in [
            ('dice2', 36),
            ('dice3', 216),
            ('coins', 16),
            ('cards2', 1326),
            ('cards3', 22100),
            ('clue6', 11),
            ('cardsclue', 1001),
            ('card1', 52),
            ('duel', 216),
            ('efron', 1296),
            ('coins8', 256),
            ('urn', 336),
            ('letters', 120),
            ('birthday', 20736),
            ('integer', 100),
        ]:
            outcomes, rows = sample_space(f)
            self.assertEqual(len(outcomes), size)
            self.assertEqual(len(rows), size)
        self.assertTrue(all(len(set(o)) == 3 for o in sample_space('cards3')[0]))

    def test_known_probabilities(self):
        checks = [
            ('dice2', event('sum', 'gt', 7, ''), Fraction(15, 36)),
            ('dice2', event('product', 'gt', 20, ''), Fraction(6, 36)),
            ('cards2', event('same_suit', 'eq', 1, ''), Fraction(12, 51)),
            ('cards3', event('aces', 'ge', 1, ''), 1 - Fraction(math.comb(48, 3), math.comb(52, 3))),
            ('coins', event('sum', 'eq', 2, ''), Fraction(6, 16)),
        ]
        for family, e, expected in checks:
            rows = sample_space(family)[1]
            self.assertEqual(Fraction(sum(wins(e, r) for r in rows), len(rows)), expected)

    def test_bank_probabilities(self):
        for family in FAMILIES:
            rows = sample_space(family)[1]
            bank = event_bank(family)
            for e in random.Random(1).sample(bank, min(12, len(bank))):
                self.assertEqual(e['count'], sum(wins(e, r) for r in rows))

    def test_puzzle_probabilities(self):
        def p(family, metric, op, target):
            rows = sample_space(family)[1]
            return Fraction(sum(wins(event(metric, op, target, ''), r) for r in rows), len(rows))

        self.assertEqual(p('clue6', 'min', 'eq', 6), Fraction(1, 11))
        for pair in ('AB', 'BC', 'CD', 'DA'):  # Efron's dice form a cycle
            self.assertEqual(p('efron', pair, 'eq', 1), Fraction(2, 3))
        self.assertEqual(p('letters', 'fixed', 'eq', 0), Fraction(44, 120))
        self.assertEqual(p('urn', 'third_blue', 'eq', 1), Fraction(3, 8))
        self.assertEqual(p('cardsclue', 'red', 'eq', 2), Fraction(325, 1001))
        self.assertEqual(p('duel', 'alice_win', 'eq', 1), Fraction(125, 216))
        self.assertEqual(p('duel', 'bob_win', 'eq', 1), p('duel', 'both_beat', 'eq', 1))
        self.assertEqual(p('coins8', 'run', 'ge', 3), Fraction(107, 256))
        self.assertGreater(p('coins8', 'hht', 'eq', 1), p('coins8', 'hth', 'eq', 1))
        self.assertEqual(p('birthday', 'distinct', 'eq', 4), Fraction(12 * 11 * 10 * 9, 12**4))
        self.assertEqual(p('integer', 'digit_sum', 'ge', 10), Fraction(45, 100))

    def test_ev_and_kelly(self):
        e = {'p': 0.5, 'odds': 1.5, 'count': 1, 'total': 2}
        a = analyse(e)
        self.assertAlmostEqual(a['ev'], 0.25)
        self.assertAlmostEqual(a['kelly'], 1 / 6)
        self.assertAlmostEqual(a['breakeven'], 0.4)
