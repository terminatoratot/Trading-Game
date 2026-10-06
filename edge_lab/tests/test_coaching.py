"""Joint Kelly sizing and per-round coaching verdicts."""

import json
import unittest

from edge_lab.coaching import joint_kelly, payoff_table, win_patterns
from edge_lab.game import Session
from edge_lab.probability import event, sample_space
from edge_lab.tests.helpers import guess


class CoachingTests(unittest.TestCase):
    def test_joint_kelly(self):
        one = [dict(event('odd', 'eq', 1, ''), p=0.5, odds=1.5)]
        table = payoff_table(one, win_patterns(one, sample_space('dice2')[1]))
        self.assertAlmostEqual(joint_kelly(table, 1)[0], 1 / 6, places=4)
        bad = [dict(event('odd', 'eq', 1, ''), p=0.5, odds=0.8)]
        table = payoff_table(bad, win_patterns(bad, sample_space('dice2')[1]))
        self.assertEqual(joint_kelly(table, 1), [0.0])

    def test_coaching_flags(self):
        s = Session({'seed': 'coach'})
        s.current['family'] = 'dice2'
        s.current['events'] = [
            dict(event('odd', 'eq', 1, 'Odd'), id='0', p=0.5, count=18, total=36, odds=0.8),
            dict(event('max', 'eq', 6, 'A six'), id='1', p=11 / 36, count=11, total=36, odds=3.0),
        ]
        r = s.settle({'round': 1, 'stakes': {'0': 10}, 'estimates': guess(s, **{'0': 90})})
        kinds = [e['coach']['kind'] for e in r['events']]
        self.assertEqual(kinds, ['bad_buy', 'missed_edge'])
        self.assertIn('estimate_flip', r['coaching']['flags'])
        self.assertAlmostEqual(
            r['events'][1]['coach']['suggested_stake'], 1000 * ((11 / 36 * 4 - 1) / 3) / 2, places=1
        )
        json.dumps(r, allow_nan=False)
        self.assertTrue(s.summary()['coaching']['focus'])

    def test_hedge_leg_not_called_bad_buy(self):
        # 1/1.8 + 1/2.5 < 1, so these complementary prices can be combined for a guaranteed profit.
        s = Session({'seed': 'hedge'})
        s.current['family'] = 'dice2'
        s.current['events'] = [
            dict(event('odd', 'eq', 1, 'Odd'), id='0', p=0.5, count=18, total=36, odds=0.8),
            dict(event('odd', 'eq', 0, 'Even'), id='1', p=0.5, count=18, total=36, odds=1.5),
        ]
        r = s.settle({'round': 1, 'stakes': {'0': 10, '1': 8}, 'estimates': guess(s)})
        self.assertEqual([e['coach']['kind'] for e in r['events']], ['hedge', 'good_buy'])
        self.assertNotIn('bad_buy', r['coaching']['flags'])
