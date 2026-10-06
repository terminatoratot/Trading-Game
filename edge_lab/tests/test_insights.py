"""Finding patterns in past answers, and the practice and drill modes built on them."""

import random
import unittest

from edge_lab.game import Drill, Session
from edge_lab.insights import clean_log, practice_focus, profile
from edge_lab.probability import FAMILIES, event_bank


def fake_log(n=60, bias=0.0, stretch=1.0, bad_buys=False, family=None, seed=1):
    """Answers to real questions, with estimates distorted by a bias and a stretch around 50%."""
    rng = random.Random(seed)
    families = [family] if family else list(FAMILIES)
    log = []
    for _ in range(n):
        fam = rng.choice(families)
        e = rng.choice(event_bank(fam))
        estimate = min(100, max(0, 50 + stretch * (100 * e['p'] - 50) + bias))
        entry = {
            'fam': fam,
            'm': e['metric'],
            'q': e['label'],
            'p': e['p'],
            'e': estimate,
            'h': 0,
            'mode': 'interview',
        }
        if bad_buys:
            entry.update(be=e['p'] + 0.02, ev=-0.05, k='bad_buy', s=0.02, sug=0)
        log.append(entry)
    return log


class InsightTests(unittest.TestCase):
    def test_log_is_sanitised(self):
        junk = [
            None,
            'x',
            {'fam': 'nope', 'p': 0.5},
            {'fam': 'dice2', 'p': 2},
            {'fam': 'dice2', 'p': 0.5, 'e': 500},
            {'fam': 'dice2', 'p': 0.5, 'e': True},
        ]
        cleaned = clean_log(junk)
        self.assertEqual(len(cleaned), 2)
        self.assertTrue(all(x['e'] is None for x in cleaned))
        self.assertEqual(profile('not a list')['estimates'], 0)

    def test_needs_enough_answers(self):
        pr = profile(fake_log(5))
        self.assertFalse(pr['ready'])
        self.assertIsNone(pr['slope'])

    def test_accurate_player_has_no_estimation_issues(self):
        pr = profile(fake_log(80))
        self.assertAlmostEqual(pr['mean_abs_error'], 0, places=6)
        self.assertAlmostEqual(pr['slope'], 1, places=6)
        self.assertFalse([i for i in pr['issues'] if i['key'] in ('compress', 'accuracy')])

    def test_estimates_hugging_fifty_are_detected(self):
        pr = profile(fake_log(80, stretch=0.5))
        keys = [i['key'] for i in pr['issues']]
        self.assertIn('compress', keys)
        self.assertIn('over_rare', keys)  # pulled toward 50%, rare events read too high
        focus = practice_focus(pr)
        self.assertTrue({'rare', 'likely'} <= set(focus['bands']))

    def test_betting_habits(self):
        pr = profile(fake_log(40, bad_buys=True))
        keys = [i['key'] for i in pr['issues']]
        self.assertIn('bad_buys', keys)
        self.assertIn('thin_edges', keys)
        self.assertIn('thin', practice_focus(pr)['prices'])

    def test_weak_topic_is_targeted(self):
        log = fake_log(40) + fake_log(12, bias=20, family='letters', seed=2)
        pr = profile(log)
        self.assertEqual(pr['topics'][0]['family'], 'letters')
        focus = practice_focus(pr)
        self.assertEqual(max(focus['families'], key=focus['families'].get), 'letters')
        seen = [
            Session({'mode': 'practice', 'focus': focus, 'seed': str(s)}).current['family'] for s in range(60)
        ]
        self.assertGreater(
            seen.count('letters'), 60 / len(FAMILIES) * 2
        )  # dealt far more often than by chance

    def test_practice_board_notes_its_targets(self):
        focus = practice_focus(profile(fake_log(80, stretch=0.5, bad_buys=True)))
        s = Session({'mode': 'practice', 'focus': focus, 'difficulty': 'medium'})
        self.assertIn('near-fair prices', s.public()['round']['focus_note'])
        self.assertNotIn('answer', s.public()['round']['events'][0])  # practice is unaided


class DrillTests(unittest.TestCase):
    def test_streaks_and_scoring(self):
        d = Drill({'difficulty': 'hard', 'seconds': 60})
        truth = 100 * d.question['event']['p']
        out = d.answer({'number': 1, 'estimate': truth})
        self.assertTrue(out['feedback']['within'])
        self.assertEqual(out['drill']['streak'], 1)
        truth = 100 * d.question['event']['p']
        out = d.answer({'number': 2, 'estimate': 0 if truth > 50 else 100})
        self.assertFalse(out['feedback']['within'])
        self.assertEqual((out['drill']['streak'], out['drill']['best']), (0, 1))
        with self.assertRaises(ValueError):
            d.answer({'number': 99, 'estimate': 10})
        summary = d.summary()
        self.assertEqual((summary['answered'], summary['correct']), (2, 1))
        self.assertEqual(len(summary['misses']), 1)

    def test_late_answers_do_not_count(self):
        d = Drill({'seconds': 30})
        d.deadline -= 60
        out = d.answer({'number': 1, 'estimate': 50})
        self.assertIsNone(out['feedback'])
        self.assertTrue(out['drill']['finished'])
        self.assertEqual(d.summary()['answered'], 0)

    def test_question_is_hidden_until_answered(self):
        q = Drill({}).public()['question']
        self.assertNotIn('p', q)
        self.assertIn('label', q)
