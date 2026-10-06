"""Multiplayer rooms: shared boards, hidden bets, host handover."""

import unittest

from edge_lab.rooms import Room
from edge_lab.tests.helpers import guess


class RoomTests(unittest.TestCase):
    def test_room_shared_boards_and_outcome(self):
        room = Room('ABCD', {'name': 'Host', 'rounds': 3, 'difficulty': 'hard'})
        guest = room.add('Guest')
        with self.assertRaises(ValueError):
            room.add('host')  # names are unique, ignoring case
        with self.assertRaises(ValueError):
            room.start(guest)  # only the host starts
        room.start(room.host)
        with self.assertRaises(ValueError):
            room.add('Late')  # no joining mid-game
        h, g = room.players[room.host]['session'], room.players[guest]['session']
        for number in range(1, 4):
            self.assertEqual(h.current['events'], g.current['events'])
            self.assertEqual(h.current['events'], room.dealer.current['events'])
            self.assertNotIn('answer', room.view(guest)['board']['events'][0])
            with self.assertRaises(ValueError):
                room.submit(guest, {'round': number, 'stakes': {}, 'estimates': {}})
            room.submit(room.host, {'round': number, 'stakes': {'0': 10}, 'estimates': guess(h)})
            self.assertEqual(room.state, 'playing')  # guest has not locked yet
            self.assertNotIn('result', room.view(room.host))  # and nobody sees the roll early
            self.assertNotIn('comparison', room.view(room.host))  # or anyone else's bets
            room.submit(guest, {'round': number, 'stakes': {'1': 20}, 'estimates': guess(g)})
            self.assertEqual(room.state, 'reveal')
            a, b = room.view(room.host)['result'], room.view(guest)['result']
            self.assertEqual(a['outcome'], b['outcome'])
            self.assertEqual(a['events'][0]['stake'], 10)
            seen = {row['name']: row for row in room.view(guest)['comparison']['players']}
            self.assertEqual(seen['Host']['bets'][0]['stake'], 10)  # after the roll, bets are shared
            self.assertEqual(seen['Guest']['bets'][1]['stake'], 20)
            self.assertTrue(seen['Guest']['you'] and not seen['Host']['you'])
            self.assertEqual(b['events'][1]['stake'], 20)
            with self.assertRaises(ValueError):
                room.advance(guest)  # only the host moves on
            room.advance(room.host)
        self.assertEqual(room.state, 'finished')
        self.assertFalse(room.view(guest)['summary']['abandoned'])
        self.assertEqual(len(room.standings()), 2)

    def test_room_absent_player_and_clock(self):
        room = Room('WXYZ', {'name': 'Host', 'seconds': 30})
        guest = room.add('Guest')
        room.start(room.host)
        room.players[guest]['seen'] -= 60  # guest went quiet
        room.submit(
            room.host, {'round': 1, 'stakes': {}, 'estimates': guess(room.players[room.host]['session'])}
        )
        self.assertEqual(room.state, 'reveal')  # an absent player does not block
        self.assertEqual(room.view(guest)['result']['staked'], 0)
        room.advance(room.host)
        room.deadline -= 60  # the round clock ran out
        room.tick()
        self.assertEqual(room.state, 'reveal')
        room.player(guest)  # guest is back and polling
        room.leave(room.host)
        self.assertEqual(room.host, guest)  # the room passes to someone still here

    def test_room_bust_player_sits_out(self):
        room = Room('BUST', {'name': 'Host', 'bankroll': 10, 'rounds': 5})
        guest = room.add('Guest')
        room.start(room.host)
        s = room.players[guest]['session']
        s.bank = 0.0
        s.finished = True
        room.submit(
            room.host, {'round': 1, 'stakes': {}, 'estimates': guess(room.players[room.host]['session'])}
        )
        self.assertEqual(room.state, 'reveal')
        self.assertIsNone(room.view(guest)['result'])
        self.assertEqual([r['status'] for r in room.standings() if r['name'] == 'Guest'], ['out'])
        room.advance(room.host)
        self.assertEqual(room.state, 'playing')
