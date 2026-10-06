"""Live multiplayer rooms built from ordinary sessions that share a seed."""

import secrets
import time

from .game import Session, board_public, finite_number

ROOM_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'  # no I or O, which read like 1 and 0


class Room:
    """A live multiplayer game: everyone gets the same boards and one shared outcome per round.

    Each player owns an ordinary Session built from the room's seed, so boards and outcomes stay
    identical across players. A zero-stake "dealer" session keeps dealing even if every player busts.
    Bets are validated on arrival but settled only when the round closes, so nobody sees the roll early.
    """

    MAX_PLAYERS = 12
    AWAY_SECONDS = 15  # a player not polling for this long no longer holds up the round
    GRACE = 2  # transport allowance after the round clock hits zero

    def __init__(self, code, cfg):
        self.code = code
        self.seed = secrets.token_hex(4)
        self.cfg = {
            'mode': 'coach',
            'difficulty': cfg.get('difficulty', 'medium'),
            'topic': cfg.get('topic', 'mixed'),
            'bankroll': cfg.get('bankroll', 1000),
            'rounds': cfg.get('rounds', 10),
            'seed': self.seed,
        }
        self.dealer = self.new_session()  # also validates the settings
        seconds = cfg.get('seconds')
        self.seconds = None if seconds in (None, '', 0, '0') else finite_number(seconds, 'Seconds', 15, 600)
        self.players = {}  # secret -> player
        self.state = 'lobby'
        self.deadline = None
        self.host = self.add(cfg.get('name'))

    def new_session(self):
        s = Session(self.cfg)
        s.mode = 'room'  # hides coach answers from the public board
        return s

    def add(self, name):
        name = ' '.join(str(name or '').split())[:20]
        if not name:
            raise ValueError('Enter your name.')
        if self.state != 'lobby':
            raise ValueError('This game has already started. Ask the host for a new room.')
        if len(self.players) >= self.MAX_PLAYERS:
            raise ValueError('This room is full.')
        if name.lower() in {p['name'].lower() for p in self.players.values()}:
            raise ValueError('Someone in this room already uses that name.')
        secret = secrets.token_urlsafe(18)
        self.players[secret] = {
            'name': name,
            'session': None,
            'bets': None,
            'result': None,
            'seen': time.monotonic(),
            'left': False,
        }
        return secret

    def player(self, secret):
        p = self.players.get(secret)
        if p is None:
            raise ValueError('You are not in this room.')
        p['seen'] = time.monotonic()
        return p

    def present(self, p):
        return not p['left'] and time.monotonic() - p['seen'] < self.AWAY_SECONDS

    def in_play(self, p):
        s = p['session']
        return s is not None and not s.finished and s.current is not None and not s.current['settled']

    def leave(self, secret):
        p = self.player(secret)
        if self.state == 'lobby':
            del self.players[secret]
        else:
            p['left'] = True
        self.tick()

    def start(self, secret):
        self.player(secret)
        if secret != self.host:
            raise ValueError('Only the host can start the game.')
        if self.state != 'lobby':
            raise ValueError('The game has already started.')
        for p in self.players.values():
            p['session'] = self.new_session()
        self.state = 'playing'
        self.deadline = time.monotonic() + self.seconds if self.seconds else None

    def submit(self, secret, data):
        p = self.player(secret)
        if self.state != 'playing' or not self.in_play(p):
            raise ValueError('This round is already closed.')
        if self.deadline is not None and time.monotonic() > self.deadline + self.GRACE:
            raise ValueError('Time is up for this round.')
        p['session'].parse_bets(data)  # reject bad bets now, while the player can still fix them
        p['bets'] = {k: data.get(k) for k in ('round', 'stakes', 'estimates', 'auto')}
        self.tick()

    def tick(self):
        """Advance on the clock or on everyone being ready. Called on every request, under the server lock."""
        live = [p for p in self.players.values() if self.present(p)]
        if self.host not in self.players or not self.present(self.players[self.host]):
            # Hand the room to someone still here so the game never stalls on an absent host.
            for secret, p in self.players.items():
                if self.present(p):
                    self.host = secret
                    break
        if self.state != 'playing':
            return
        waiting = [p for p in live if self.in_play(p) and p['bets'] is None]
        expired = self.deadline is not None and time.monotonic() > self.deadline + self.GRACE
        if expired or not waiting:
            self.close()

    def close(self):
        number = self.dealer.current['number']
        for p in self.players.values():
            p['result'] = None
            if self.in_play(p):
                bets = p['bets'] or {'round': number, 'stakes': {}, 'estimates': {}, 'auto': True}
                p['result'] = p['session'].settle(
                    dict(bets, auto=bets.get('auto') is True or p['bets'] is None)
                )
            p['bets'] = None
        self.dealer.settle({'round': number, 'stakes': {}, 'estimates': {}, 'auto': True})
        self.state = 'reveal'

    def advance(self, secret):
        self.player(secret)
        if secret != self.host:
            raise ValueError('Only the host can move on.')
        if self.state != 'reveal':
            raise ValueError('Wait for the round to finish.')
        if self.dealer.finished:
            self.state = 'finished'
            for p in self.players.values():
                if p['session']:
                    p['session'].end()
            return
        for p in self.players.values():
            if p['session'] and not p['session'].finished:
                p['session'].next_round()
        self.dealer.next_round()
        self.state = 'playing'
        self.deadline = time.monotonic() + self.seconds if self.seconds else None

    def standings(self):
        rows = []
        start = self.dealer.start_bank
        for secret, p in self.players.items():
            s = p['session']
            history = s.history if s else []
            status = (
                'left'
                if p['left']
                else (
                    'out'
                    if s and s.bank < 0.01
                    else 'locked' if p['bets'] is not None else 'away' if not self.present(p) else 'thinking'
                )
            )
            rows.append(
                {
                    'name': p['name'],
                    'host': secret == self.host,
                    'status': status,
                    'bank': s.bank if s else start,
                    'profit': (s.bank if s else start) - start,
                    'ev': sum(r['expected_profit'] for r in history),
                    'in_range': sum(r['estimates_in_range'] for r in history),
                    'estimates': sum(len(r['events']) for r in history),
                    'last': p['result']['profit'] if p['result'] and self.state != 'playing' else None,
                }
            )
        rows.sort(key=lambda r: (-r['bank'], -r['ev'], r['name'].lower()))
        return rows

    def comparison(self, secret):
        """Everyone's bets on the board that just closed, side by side. Only built after the roll."""
        rows, events = [], None
        for key, p in self.players.items():
            r = p['result']
            if not r:
                continue  # out of bankroll, so no bets this round
            events = events or [
                {k: e[k] for k in ('id', 'label', 'odds', 'p', 'breakeven', 'ev', 'fair_odds')}
                for e in r['events']
            ]
            rows.append(
                {
                    'name': p['name'],
                    'you': key == secret,
                    'profit': r['profit'],
                    'expected': r['expected_profit'],
                    'in_range': r['estimates_in_range'],
                    'timed_out': r['timed_out'],
                    'bets': [
                        {
                            'stake': e['stake'],
                            'estimate': e['estimate'],
                            'within': e['within_range'],
                            'kind': e['coach']['kind'],
                            'profit': e['profit'],
                        }
                        for e in r['events']
                    ],
                }
            )
        rows.sort(key=lambda x: (-x['expected'], x['name'].lower()))
        return {'events': events or [], 'players': rows}

    def view(self, secret):
        p = self.players[secret]
        s = p['session']
        now = time.monotonic()
        payload = {
            'code': self.code,
            'state': self.state,
            'you': p['name'],
            'is_host': secret == self.host,
            'host_name': self.players[self.host]['name'] if self.host in self.players else '',
            'difficulty': self.cfg['difficulty'],
            'topic': self.cfg['topic'],
            'rounds': self.dealer.rounds,
            'seconds': self.seconds,
            'start_bank': self.dealer.start_bank,
            'tolerance': self.dealer.tolerance,
            'players': self.standings(),
            'round': self.dealer.current['number'] if self.dealer.current else None,
            'remaining': max(0, self.deadline - now) if self.state == 'playing' and self.deadline else None,
            'last_round': self.dealer.finished
            or (self.dealer.current or {}).get('number') == self.dealer.rounds,
        }
        if s:
            payload['me'] = {
                'session_id': s.id,
                'bank': s.bank,
                'completed': len(s.history),
                'out': s.bank < 0.01,
                'locked': p['bets'] is not None,
                'in_play': self.in_play(p),
                'ev': sum(r['expected_profit'] for r in s.history),
            }
        if self.state in ('playing', 'reveal') and self.dealer.current:
            r = self.dealer.current
            payload['board'] = dict(
                board_public(r['family'], r['number']),
                remaining=payload['remaining'],
                events=[{k: e[k] for k in ('id', 'label', 'odds')} for e in r['events']],
            )
        if self.state == 'reveal':
            payload['result'] = p['result']
            payload['comparison'] = self.comparison(secret)
        if self.state == 'finished' and s:
            payload['summary'] = s.summary()
        return payload
