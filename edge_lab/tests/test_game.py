"""Single-player sessions: dealing, validation, settling and summaries."""

import csv
import io
import time
import unittest

from edge_lab.game import LEVEL, Session, dealable
from edge_lab.probability import FAMILIES, TOPICS, event
from edge_lab.tests.helpers import guess


class SessionTests(unittest.TestCase):
    def test_shared_outcome_hedge(self):
        s = Session({'seed': 'test'})
        s.current['family'] = 'dice2'
        s.current['events'] = [
            dict(event('odd', 'eq', v, 'Parity'), id=str(v), p=0.5, count=18, total=36, odds=1)
            for v in (0, 1)
        ]
        r = s.settle({'round': 1, 'stakes': {'0': 100, '1': 100}, 'estimates': guess(s)})
        self.assertEqual(r['profit'], 0)
        self.assertEqual(r['worst'], 0)
        self.assertEqual(r['best'], 0)
        self.assertEqual(r['loss_probability'], 0)
        self.assertEqual(sum(e['won'] for e in r['events']), 1)

    def test_seed_replay(self):
        a, b = Session({'seed': 'replay', 'rounds': 5}), Session({'seed': 'replay', 'rounds': 5})
        for i in range(5):
            self.assertEqual(a.current['events'], b.current['events'])
            ra = a.settle({'round': i + 1, 'stakes': {'0': 5}, 'estimates': guess(a)})
            rb = b.settle({'round': i + 1, 'stakes': {'0': 5}, 'estimates': guess(b)})
            self.assertEqual(ra['outcome'], rb['outcome'])
            self.assertEqual(ra['bank_after'], rb['bank_after'])
            a.next_round()
            b.next_round()
        self.assertTrue(a.finished)

    def test_validation_and_double_settle(self):
        s = Session({})
        for stake in (-1, float('nan'), float('inf'), 1001):
            with self.assertRaises(ValueError):
                s.settle({'round': 1, 'stakes': {'0': stake}, 'estimates': guess(s)})
        with self.assertRaises(ValueError):
            s.settle({'round': 1, 'stakes': {'0': 600, '1': 600}, 'estimates': guess(s)})
        with self.assertRaises(ValueError):
            s.next_round()
        with self.assertRaises(ValueError):
            s.settle({'round': 99, 'stakes': {}})
        s.settle({'round': 1, 'stakes': {}, 'estimates': guess(s)})
        with self.assertRaises(ValueError):
            s.settle({'round': 1, 'stakes': {}, 'estimates': guess(s)})

    def test_estimates_required(self):
        s = Session({'seed': 'req'})
        for bad in ({}, {'0': 50, '1': 50, '2': 50}, {'0': 50, '1': 50, '2': 50, '3': ''}):
            with self.assertRaises(ValueError):
                s.settle({'round': 1, 'stakes': {}, 'estimates': bad})
        with self.assertRaises(ValueError):
            s.settle({'round': 1, 'stakes': {}, 'estimates': guess(s, **{'0': 101})})
        self.assertFalse(s.current['settled'])  # a rejected submit must not consume the round
        self.assertEqual(s.history, [])
        r = s.settle({'round': 1, 'stakes': {}, 'estimates': guess(s)})
        self.assertTrue(r['events'][0]['within_range'] is not None)

    def test_auto_submit_allows_blank_estimates(self):
        s = Session({'seed': 'auto'})
        r = s.settle({'round': 1, 'stakes': {}, 'estimates': {}, 'auto': True})
        self.assertTrue(all(e['within_range'] is None for e in r['events']))
        self.assertEqual(r['estimates_in_range'], 0)

    def test_estimate_tolerance_by_difficulty(self):
        for difficulty, tol in (('easy', 10), ('medium', 5), ('hard', 2)):
            s = Session({'seed': 'tol', 'difficulty': difficulty})
            self.assertEqual(s.tolerance, tol)
            true = [100 * e['p'] for e in s.current['events']]
            inside = true[0] + tol - 0.01 if true[0] + tol <= 100 else true[0] - tol + 0.01
            outside = true[1] + tol + 0.5 if true[1] + tol + 0.5 <= 100 else true[1] - tol - 0.5
            r = s.settle({'round': 1, 'stakes': {}, 'estimates': guess(s, **{'0': inside, '1': outside})})
            self.assertTrue(r['events'][0]['within_range'])
            self.assertFalse(r['events'][1]['within_range'])
            self.assertEqual(r['tolerance'], tol)

    def test_abandoned_sessions(self):
        early = Session({'seed': 'quit', 'rounds': 3})
        early.settle({'round': 1, 'stakes': {}, 'estimates': guess(early)})
        self.assertTrue(early.end()['abandoned'])
        self.assertTrue(early.end()['abandoned'])  # ending twice must not launder the session
        done = Session({'seed': 'done', 'rounds': 1})
        done.settle({'round': 1, 'stakes': {}, 'estimates': guess(done)})
        self.assertTrue(done.finished)
        self.assertFalse(done.end()['abandoned'])
        timed = Session({'mode': 'sprint', 'minutes': 1})
        timed.deadline = time.monotonic() - 1
        self.assertFalse(timed.end()['abandoned'])
        self.assertTrue(Session({}).end()['abandoned'])  # nothing played

    def test_round_graphic_fields(self):
        for topic, kind in (
            ('dice', 'dice'),
            ('cards', 'cards'),
            ('coins', 'coins'),
        ):  # kind drives the graphic
            r = Session({'topic': topic}).public()['round']
            self.assertEqual(r['kind'], kind)
            self.assertEqual(r['count'], FAMILIES[r['family']]['n'])
            self.assertEqual(len(r['slots']), r['count'])

    def test_every_board_can_be_dealt(self):
        for topic in ('mixed',) + TOPICS:
            for difficulty in ('easy', 'medium', 'hard'):
                s = Session({'topic': topic, 'difficulty': difficulty, 'rounds': 1})
                self.assertGreaterEqual(len(s.current['events']), 3)
        for family in FAMILIES:
            self.assertTrue(any(dealable(family, lv, 3 if lv == 1 else 4) for lv in (1, 2, 3)), family)

    def test_levels_stay_apart(self):
        for difficulty, level in LEVEL.items():
            for seed in range(40):
                s = Session({'seed': str(seed), 'difficulty': difficulty, 'rounds': 1})
                levels = [e['level'] for e in s.current['events']]
                self.assertEqual(levels.count(level) >= 2, True, (difficulty, s.current['family']))
                self.assertTrue(all(lv in (level, level - 1) for lv in levels))
                if difficulty == 'easy':
                    self.assertTrue(all(lv == 1 for lv in levels))

    def test_hidden_answers(self):
        for mode in ('interview', 'sprint'):
            s = Session({'mode': mode})
            for e in s.public()['round']['events']:
                self.assertEqual(set(e), {'id', 'label', 'odds'})
        self.assertIn('answer', Session({'mode': 'coach'}).public()['round']['events'][0])

    def test_expired_round(self):
        s = Session({'mode': 'interview'})
        s.current['deadline'] = time.monotonic() - 3
        r = s.settle({'round': 1, 'stakes': {'0': 100}})
        self.assertTrue(r['timed_out'])
        self.assertEqual(r['staked'], 0)

    def test_summary_and_export(self):
        s = Session({'seed': '=2+2', 'rounds': 1})
        r = s.settle({'round': 1, 'stakes': {'0': 10}, 'estimates': guess(s, **{'0': 25})})
        summary = s.summary()
        self.assertTrue(s.finished)
        self.assertEqual(summary['estimates'], len(r['events']))
        self.assertEqual(summary['estimates_total'], len(r['events']))
        self.assertAlmostEqual(summary['profit'], r['profit'])
        self.assertAlmostEqual(sum(x['probability'] for x in r['distribution']), 1)
        rows = list(csv.reader(io.StringIO(s.csv())))
        self.assertEqual(rows[1][0], "'=2+2")
