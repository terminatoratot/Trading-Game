"""The market-making card game: fair values, settlement, the P&L check, events and bots."""

import itertools
import random
import re
import statistics
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from edge_lab import trading
from edge_lab.trading import EASY, MEDIUM, TradingGame, bot_order, bot_quote, fair_value


def play_round(g, side='pass', size=0):
    """Take the current round to its result with a correct P&L answer."""
    r = g.round
    if r['phase'] == 'event':
        g.act({'action': 'begin'})
    if r['maker'] == 0:
        mid = round(r['public']['mean'])
        g.act({'action': 'quote', 'bid': mid - g.min_spread, 'ask': mid})
    else:
        if side != 'pass':
            size = min(size, g.limits_for(0)[side])
            side = side if size >= 1 else 'pass'
        g.act({'action': 'order', 'side': side, 'size': size})
    if g.check:
        g.act({'action': 'answer', 'answer': r['result']['pnl'][0]})
    return r


class FairValueTests(unittest.TestCase):
    def test_matches_brute_force(self):
        shown = [12]  # K♣
        ev = MEDIUM[2]  # the highest card counts double
        pool = [c for c in range(52) if c not in shown]
        values = [ev['value'](shown + list(h)) for h in itertools.combinations(pool, 2)]
        fv = fair_value(ev, shown, 2)
        self.assertAlmostEqual(fv['mean'], statistics.fmean(values))
        self.assertEqual(fv['hands'], len(values))

    def test_news_conditions_the_hidden_cards(self):
        news = next(e for e in MEDIUM if e['key'] == 'face_news')
        plain, informed = fair_value(None, [], 2), fair_value(news, [], 2)
        self.assertGreater(informed['mean'], plain['mean'])

    def test_large_hands_are_sampled(self):
        fv = fair_value(None, [], 6, seed=1)
        self.assertEqual(fv['hands'], trading.SAMPLES)
        self.assertFalse(fv['exact'])
        self.assertTrue(fair_value(None, [0], 3)['exact'])
        self.assertAlmostEqual(fv['mean'], 48, delta=0.3)  # six cards averaging 8

    def test_insider_knows_more(self):
        ace, king = 0, 12
        self.assertLess(
            fair_value(None, [], 3, insider_card=ace)['mean'],
            fair_value(None, [], 3, insider_card=king)['mean'],
        )


class GameTests(unittest.TestCase):
    def test_hidden_cards_stay_hidden_until_settled(self):
        g = TradingGame({'difficulty': 'medium', 'mode': 'taker', 'events': False})
        cards = g.public()['round']['cards']
        self.assertEqual(sum(c['up'] for c in cards), g.shown)
        self.assertTrue(all('label' not in c for c in cards if not c['up']))
        g.act({'action': 'order', 'side': 'pass'})
        self.assertTrue(all(c['up'] for c in g.public()['round']['cards']))

    def test_money_is_conserved(self):
        g = TradingGame({'difficulty': 'hard', 'rounds': 8, 'check': False, 'track': False})
        while not g.finished:
            r = play_round(g, 'buy', 5)
            self.assertEqual(sum(r['result']['pnl']), 0)
            g.act({'action': 'next'})
        self.assertEqual(sum(g.scores), 4 * g.budget)

    def test_quote_rules(self):
        g = TradingGame({'mode': 'maker', 'events': False, 'min_spread': 2, 'max_spread': 4})
        for bid, ask in ((30, 31), (30, 35), (31, 30)):
            with self.assertRaises(ValueError):
                g.act({'action': 'quote', 'bid': bid, 'ask': ask})
        with self.assertRaises(ValueError):
            g.act({'action': 'order', 'side': 'buy', 'size': 1})
        g.act({'action': 'quote', 'bid': 30, 'ask': 33})
        self.assertEqual(g.round['phase'], 'check')

    def test_orders_need_a_valid_size(self):
        g = TradingGame({'mode': 'taker', 'events': False})
        for bad in (0, 10_000, 'x', True):
            with self.assertRaises(ValueError):
                g.act({'action': 'order', 'side': 'buy', 'size': bad})

    def test_pnl_check(self):
        g = TradingGame({'mode': 'taker', 'events': False})
        g.act({'action': 'order', 'side': 'buy', 'size': 10})
        actual = g.round['result']['pnl'][0]
        g.act({'action': 'answer', 'answer': str(actual + 1)})
        self.assertFalse(g.round['check']['correct'])
        self.assertEqual(g.scores[0], g.budget + min(actual, 0) - trading.CHECK_PENALTY)
        g2 = TradingGame({'mode': 'taker', 'events': False})
        g2.act({'action': 'order', 'side': 'sell', 'size': 3})
        actual = g2.round['result']['pnl'][0]
        g2.act({'action': 'answer', 'answer': '%+d' % actual})
        self.assertTrue(g2.round['check']['correct'])
        self.assertEqual(g2.scores[0], g2.budget + actual)

    def test_clock_runs_out(self):
        g = TradingGame({'mode': 'taker', 'events': False, 'seconds': 10})
        g.round['deadline'] = time.monotonic() - 60
        state = g.act({'action': 'state'})
        self.assertEqual(state['round']['phase'], 'check')
        self.assertTrue(state['round']['result']['timed_out'])
        self.assertEqual(g.round['orders'][0], ('pass', 0))

    def test_event_tiers(self):
        easy_keys = {e['key'] for e in EASY}
        for _ in range(30):
            g = TradingGame({'difficulty': 'easy'})
            ev = g.round['event']
            self.assertTrue(ev is None or ev['key'] in easy_keys)
        hard_keys = set()
        for _ in range(60):
            ev = TradingGame({'difficulty': 'hard'}).round['event']
            hard_keys.add(ev['key'] if ev else None)
        self.assertTrue(any('+' in k for k in hard_keys if k))  # stacked events appear
        self.assertNotIn(None, hard_keys)  # hard rounds always have an event

    def test_finished_game_reports_rankings(self):
        g = TradingGame({'rounds': 2, 'difficulty': 'easy'})
        while not g.finished:
            play_round(g)
            g.act({'action': 'next'})
        s = g.public()['summary']
        self.assertEqual(len(s['rankings']), 4)
        self.assertEqual(s['rounds'], 2)
        self.assertIn(s['place'], (1, 2, 3, 4))


class RulesTests(unittest.TestCase):
    def test_card_values(self):
        self.assertEqual([trading.rank(c) for c in range(13)], list(range(2, 15)))
        self.assertEqual(trading.card_label(12), 'A♣')
        self.assertEqual(trading.card_label(9), 'J♣')
        self.assertAlmostEqual(fair_value(None, [], 1)['mean'], 8)

    def test_event_lessons_match_the_maths(self):
        events = {e['key']: e for e in EASY + MEDIUM}
        per_card = lambda key: fair_value(events[key], [], 1)['mean']
        self.assertAlmostEqual(per_card('even'), 8)
        self.assertAlmostEqual(per_card('odd'), 8)
        self.assertAlmostEqual(per_card('no_faces'), 6.8)
        self.assertAlmostEqual(per_card('high'), 11)
        self.assertAlmostEqual(per_card('low'), 4.5)
        self.assertAlmostEqual(per_card('ace_low'), 7)
        self.assertAlmostEqual(per_card('blackjack'), 95 / 13)
        self.assertAlmostEqual(per_card('hearts_double'), 10)

    def test_order_limits(self):
        # Long: 500 // 30 = 16 units. Short: worst case 56 against a bid of 28 risks 28 a unit, 500 // 28 = 17.
        self.assertEqual(trading.order_limits(500, 28, 30, 56, 8), {'buy': 16, 'sell': 17})
        self.assertEqual(trading.order_limits(0, 28, 30, 56, 8), {'buy': 0, 'sell': 0})
        g = TradingGame({'mode': 'taker', 'events': False, 'budget': 100})
        cap = g.limits_for(0)['buy']
        with self.assertRaises(ValueError):
            g.act({'action': 'order', 'side': 'buy', 'size': cap + 1})
        g.act({'action': 'order', 'side': 'buy', 'size': cap})

    def test_open_outcry_first_shout_wins(self):
        g = TradingGame({'mode': 'outcry', 'events': False})
        self.assertEqual(g.round['phase'], 'outcry')
        self.assertNotIn('shouts', g.public()['round'])  # reaction times stay secret
        g.act({'action': 'quote', 'bid': 30, 'ask': 32})  # instant: beats every bot
        self.assertEqual(g.round['maker'], 0)
        self.assertEqual(g.round['quote'], (30, 32))

        late = TradingGame({'mode': 'outcry', 'events': False})
        late.round['opened'] -= 30
        state = late.act({'action': 'state'})
        r = late.round
        self.assertEqual(state['round']['phase'], 'decide')
        self.assertEqual(r['maker'], min(r['shouts'], key=r['shouts'].get))
        self.assertEqual(r['quote'], r['bot_quotes'][r['maker']])

    def test_mental_balance_check(self):
        g = TradingGame({'difficulty': 'hard', 'rounds': 2, 'check': False})
        self.assertIsNone(g.public()['players'][0]['score'])  # hidden while you track it
        while not g.awaiting_balance:
            play_round(g)
            g.act({'action': 'next'})
        actual = g.scores[0]
        state = g.act({'action': 'balance', 'answer': str(actual + 1)})
        self.assertTrue(state['finished'])
        self.assertFalse(state['summary']['final_check']['correct'])
        self.assertEqual(g.scores[0], actual - trading.CHECK_PENALTY)


class FeedbackTests(unittest.TestCase):
    def taker_round(self, fair, bid, ask, side, size, value, limits=None):
        g = TradingGame({'mode': 'taker', 'events': False, 'check': False})
        r = g.round
        r['public'] = dict(r['public'], mean=fair, sd=6)
        r['quote'] = (bid, ask)
        r['your_limits'] = limits or {'buy': 16, 'sell': 16}
        r['orders'] = {0: (side, size)}
        r['result'] = {
            'value': value,
            'trades': [],
            'pnl': [
                (value - ask) * size if side == 'buy' else (bid - value) * size if side == 'sell' else 0,
                0,
                0,
                0,
            ],
            'timed_out': False,
        }
        return g.feedback(r)

    def test_clean_good_trade_has_no_extra_advice(self):
        fb = self.taker_round(fair=34, bid=28, ask=30, side='buy', size=10, value=36)
        self.assertEqual(fb['title'], 'Good trade')
        self.assertIsNone(fb['better'])
        self.assertEqual(fb['notes'], [])

    def test_lucky_negative_edge_trade_is_flagged(self):
        fb = self.taker_round(fair=34, bid=36, ask=38, side='buy', size=5, value=45)
        self.assertEqual(fb['title'], 'Negative-edge trade')
        self.assertIn('Better', fb['better'])
        self.assertTrue(any('fell your way' in n for n in fb['notes']))

    def test_undersized_strong_edge_is_mentioned(self):
        fb = self.taker_round(fair=40, bid=28, ask=30, side='buy', size=1, value=41)
        self.assertEqual(fb['title'], 'Good trade')
        self.assertTrue(any('room' in n for n in fb['notes']))

    def test_unaffordable_edge_is_not_called_a_mistake(self):
        fb = self.taker_round(
            fair=34, bid=28, ask=30, side='pass', size=0, value=33, limits={'buy': 0, 'sell': 0}
        )
        self.assertEqual(fb['title'], 'No affordable trade')
        self.assertIsNone(fb['better'])

    def test_missed_edge_names_the_better_play(self):
        fb = self.taker_round(fair=34, bid=28, ask=30, side='pass', size=0, value=33)
        self.assertEqual(fb['title'], 'Missed edge')
        self.assertIn('buy', fb['better'])


class ExplanationTests(unittest.TestCase):
    def last_number(self, tex):
        return float(re.findall(r'-?\d+\.\d\d', tex)[-1])

    def test_every_event_derivation_reaches_fair_value(self):
        rng = random.Random(5)
        events = (
            [None]
            + EASY
            + MEDIUM
            + trading.hard_events(4)
            + [trading.stacked(random.Random(i), 4) for i in range(6)]
        )
        for ev in events:
            pool = trading.hidden_pool(ev, [])
            hand = rng.sample(pool, 4)
            while ev and ev['news'] and not ev['news'](tuple(hand[1:])):
                hand = rng.sample(pool, 4)
            public = fair_value(ev, hand[:1], 3, seed=3)
            steps = trading.explain(ev, hand[:1], 3, 3, public)['steps']
            self.assertAlmostEqual(
                self.last_number(steps[-1]['tex']), public['mean'], delta=0.011, msg=ev and ev['key']
            )

    def test_pair_bonus_shows_the_counting(self):
        ev = next(e for e in MEDIUM if e['key'] == 'pair_bonus')
        four = 2  # the 4 of clubs, as in the screenshot that prompted this
        ex = trading.explain(ev, [four], 3, 0, fair_value(ev, [four], 3))
        self.assertIn(r'\binom{12}{3}', ex['steps'][1]['tex'])
        self.assertIn('raises fair value by 6.48, from 28.24 to 34.71', ex['summary'])

    def test_result_payload_carries_the_math(self):
        g = TradingGame({'mode': 'taker', 'check': False})
        if g.round['phase'] == 'event':
            g.act({'action': 'begin'})
        state = g.act({'action': 'order', 'side': 'pass'})
        self.assertTrue(state['round']['math']['steps'])


class ShortcutTests(unittest.TestCase):
    def test_shortcuts_land_close_to_exact_fair_value(self):
        rng = random.Random(9)
        for n in (4, 5):
            events = (
                [None]
                + EASY
                + MEDIUM
                + trading.hard_events(n)
                + [trading.stacked(random.Random(i), n) for i in range(12)]
            )
            for ev in events:
                pool = trading.hidden_pool(ev, [])
                hand = rng.sample(pool, n)
                while ev and ev['news'] and not ev['news'](tuple(hand[1:])):
                    hand = rng.sample(pool, n)
                quick = trading.shortcut(ev, hand[:1], n - 1)
                exact = fair_value(ev, hand[:1], n - 1, seed=2)['mean']
                self.assertLess(abs(quick['estimate'] - exact), 3.5, msg=ev and ev['key'])
                self.assertIsNone(
                    re.search(r'\\\\[a-zA-Z]', quick['tex']), msg=quick['tex']
                )  # '\\cdot' would break the typesetting

    def test_screenshot_example(self):
        ev = trading.event(
            'x', '', '', deck=EASY[3]['deck'], value=MEDIUM[1]['value'], rule='blackjack', deck_key='high'
        )
        quick = trading.shortcut(ev, [6], 3)  # the 8 of clubs showing
        self.assertIn(r'\frac{68}{7}', quick['tex'])
        self.assertAlmostEqual(quick['estimate'], 8 + 3 * 68 / 7)


class BotTests(unittest.TestCase):
    def test_quotes_respect_spread_limits(self):
        for sd in (0, 3, 30):
            bid, ask = bot_quote(trading.BOTS[2], 28.4, sd, 2, 5)
            self.assertTrue(2 <= ask - bid <= 5)

    def test_bots_trade_toward_value(self):
        sharp = trading.BOTS[1]
        self.assertEqual(bot_order(sharp, 40, 30, 32)[0], 'buy')
        self.assertEqual(bot_order(sharp, 20, 30, 32)[0], 'sell')
        self.assertEqual(bot_order(sharp, 31, 30, 32), ('pass', 0))


class LeaderboardTests(unittest.TestCase):
    def test_only_named_completed_games_are_recorded(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            trading, 'LEADERBOARD', Path(folder) / 'lb.json'
        ):
            for name in ('', 'Ana'):
                g = TradingGame({'rounds': 2, 'name': name, 'check': False})
                while not g.finished:
                    play_round(g)
                    g.act({'action': 'next'})
            board = trading.leaderboard()
            self.assertEqual([row['name'] for row in board], ['Ana'])
            self.assertEqual(board[0]['games'], 1)


if __name__ == '__main__':
    unittest.main()
