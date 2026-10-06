"""The local web server: static files plus a small JSON API.

Usage: python3 edge.py [--port 8765] [--share] [--no-browser] [--self-test]
"""

import argparse
import json
import secrets
import socket
import threading
import time
import unittest
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .game import Drill, Session
from .insights import practice_focus, profile
from .rooms import ROOM_LETTERS, Room
from .trading import TradingGame, leaderboard

STATIC = Path(__file__).parent / 'static'
CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
    '.txt': 'text/plain; charset=utf-8',
}
MAX_BODY = 2_000_000  # the question log for insights can run to a few hundred kilobytes
MAX_SESSIONS = 500  # detailed sessions kept in memory; the browser keeps its own summaries
MAX_ROOMS = 200
IDLE_ROOM_SECONDS = 1800


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, shared=False):
        super().__init__(address, Handler)
        self.shared = shared
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.sessions = {}
        self.drills = {}
        self.rooms = {}
        self.games = {}

    def keep(self, store, key, value):
        """Store an object, dropping the oldest once the store is full."""
        if len(store) >= MAX_SESSIONS:
            del store[next(iter(store))]
        store[key] = value


class Handler(BaseHTTPRequestHandler):
    # Route methods are prefixed api_ so they can never shadow the base class's own hooks (such as finish).
    server_version = 'EdgeLab/2.0'

    def log_message(self, fmt, *args):
        pass

    # ---- plumbing

    def send(self, status, payload, content_type='application/json; charset=utf-8'):
        if not isinstance(payload, (str, bytes)):
            payload = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        raw = payload.encode('utf-8') if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(raw)

    def valid_host(self):
        if self.server.shared:
            return True  # reachable by other devices or through a tunnel, whose Host header we cannot predict
        port = self.server.server_port
        return self.headers.get('Host') in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {'error': 'Local connections only.'})
        path = urlparse(self.path).path
        pages = {'/': 'index.html', '/trading': 'trading.html'}
        if path in pages:
            page = (STATIC / pages[path]).read_text(encoding='utf-8')
            return self.send(200, page.replace('__APP_TOKEN__', self.server.token), CONTENT_TYPES['.html'])
        if path == '/favicon.ico':
            return self.send(204, b'', 'image/x-icon')
        if path.startswith('/static/'):
            file = (STATIC / path[len('/static/') :]).resolve()
            # Serve only known file types from inside the static folder.
            if STATIC.resolve() in file.parents and file.suffix in CONTENT_TYPES and file.is_file():
                return self.send(200, file.read_bytes(), CONTENT_TYPES[file.suffix])
        self.send(404, {'error': 'Not found.'})

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Edge-Token') != self.server.token:
            return self.send(403, {'error': 'Reload the app in your browser.'})
        route = ROUTES.get(urlparse(self.path).path)
        if route is None:
            return self.send(404, {'error': 'Not found.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected an object.')
            with self.server.lock:
                result = route(self, data)
            if isinstance(result, tuple):
                return self.send(200, *result)
            self.send(200, result)
        except (ValueError, TypeError, KeyError) as exc:
            self.send(400, {'error': str(exc)})

    def session(self, data):
        session = self.server.sessions.get(data.get('id'))
        if session is None:
            raise ValueError('Session unavailable. Start a new session.')
        return session

    def drill(self, data):
        drill = self.server.drills.get(data.get('id'))
        if drill is None:
            raise ValueError('Drill unavailable. Start a new drill.')
        return drill

    # ---- single-player sessions

    def api_start(self, data):
        cfg = dict(data)
        if cfg.get('mode') == 'practice':
            cfg['focus'] = practice_focus(profile(data.get('log')))
        session = Session(cfg)
        self.server.keep(self.server.sessions, session.id, session)
        return session.public()

    def api_settle(self, data):
        session = self.session(data)
        result = session.settle(data)
        return {'result': result, 'session': session.public()}

    def api_next(self, data):
        session = self.session(data)
        session.next_round()
        return session.public()

    def api_finish(self, data):
        return self.session(data).end()

    def api_export(self, data):
        return self.session(data).csv(), 'text/csv; charset=utf-8'

    def api_insights(self, data):
        return profile(data.get('log'))

    # ---- pricing drill

    def api_drill_start(self, data):
        focus = practice_focus(profile(data.get('log'))) if data.get('targeted') else None
        drill = Drill(data, focus)
        self.server.keep(self.server.drills, drill.id, drill)
        return drill.public()

    def api_drill_answer(self, data):
        return self.drill(data).answer(data)

    def api_drill_finish(self, data):
        return self.drill(data).summary()

    # ---- trading game

    def game(self, data):
        game = self.server.games.get(data.get('id'))
        if game is None:
            raise ValueError('Game unavailable. Start a new game.')
        return game

    def api_trade_start(self, data):
        game = TradingGame(data)
        self.server.keep(self.server.games, game.id, game)
        return game.public()

    def api_trade_act(self, data):
        return self.game(data).act(data)

    def api_trade_leaderboard(self, data):
        return {'rows': leaderboard()}

    # ---- multiplayer rooms

    def room(self, data):
        room = self.server.rooms.get(str(data.get('code', '')).strip().upper())
        if room is None:
            raise ValueError('No room with that code. Check it with the host.')
        return room

    def api_room_create(self, data):
        rooms = self.server.rooms
        for code, room in list(rooms.items()):
            if all(time.monotonic() - p['seen'] > IDLE_ROOM_SECONDS for p in room.players.values()):
                del rooms[code]
        if len(rooms) >= MAX_ROOMS:
            raise ValueError('The server is busy. Try again later.')
        code = ''.join(secrets.choice(ROOM_LETTERS) for _ in range(4))
        while code in rooms:
            code = ''.join(secrets.choice(ROOM_LETTERS) for _ in range(4))
        room = rooms[code] = Room(code, data)
        return {'code': code, 'secret': room.host}

    def api_room_join(self, data):
        room = self.room(data)
        return {'code': room.code, 'secret': room.add(data.get('name'))}

    def api_room_leave(self, data):
        room = self.room(data)
        room.leave(data.get('secret'))
        if not room.players:
            del self.server.rooms[room.code]
        return {'ok': True}

    def room_action(action):
        def handle(self, data):
            room, secret = self.room(data), data.get('secret')
            room.player(secret)
            room.tick()
            if action == 'start':
                room.start(secret)
                for p in room.players.values():
                    self.server.keep(
                        self.server.sessions, p['session'].id, p['session']
                    )  # enables CSV export
            elif action == 'submit':
                room.submit(secret, data)
            elif action == 'next':
                room.advance(secret)
            return room.view(secret)

        return handle

    api_room_state = room_action('state')
    api_room_start = room_action('start')
    api_room_submit = room_action('submit')
    api_room_next = room_action('next')


ROUTES = {
    '/api/start': Handler.api_start,
    '/api/settle': Handler.api_settle,
    '/api/next': Handler.api_next,
    '/api/finish': Handler.api_finish,
    '/api/export': Handler.api_export,
    '/api/insights': Handler.api_insights,
    '/api/drill/start': Handler.api_drill_start,
    '/api/drill/answer': Handler.api_drill_answer,
    '/api/drill/finish': Handler.api_drill_finish,
    '/api/trade/start': Handler.api_trade_start,
    '/api/trade/act': Handler.api_trade_act,
    '/api/trade/leaderboard': Handler.api_trade_leaderboard,
    '/api/room/create': Handler.api_room_create,
    '/api/room/join': Handler.api_room_join,
    '/api/room/leave': Handler.api_room_leave,
    '/api/room/state': Handler.api_room_state,
    '/api/room/start': Handler.api_room_start,
    '/api/room/submit': Handler.api_room_submit,
    '/api/room/next': Handler.api_room_next,
}


def lan_address():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(('10.255.255.255', 1))  # picks the outgoing interface; sends nothing
        address = probe.getsockname()[0]
        probe.close()
        return address
    except OSError:
        return '<your-computer-ip>'


def run_tests():
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).parent / 'tests'), top_level_dir=str(Path(__file__).parent.parent)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


def main():
    parser = argparse.ArgumentParser(description='EDGE LAB: a probability betting trainer.')
    parser.add_argument(
        '--port', type=int, default=8765, help='port to serve on (default 8765; 0 picks a free one)'
    )
    parser.add_argument(
        '--share',
        action='store_true',
        help='accept connections from other devices (same Wi-Fi, or a tunnel such as cloudflared)',
    )
    parser.add_argument(
        '--no-browser', action='store_true', help='print the address without opening a browser'
    )
    parser.add_argument('--self-test', action='store_true', help='run the test suite and exit')
    args = parser.parse_args()
    if args.self_test:
        run_tests()
    if not 0 <= args.port <= 65535:
        parser.error('Port must be between 0 and 65535.')
    try:
        server = AppServer(('0.0.0.0' if args.share else '127.0.0.1', args.port), shared=args.share)
    except OSError as exc:
        parser.exit(
            1,
            'Could not start the server: %s\nTry another port, for example: python3 edge.py --port 8766\n'
            % exc,
        )
    url = 'http://127.0.0.1:%d' % server.server_port
    print('\nEDGE LAB | Probability. Price. Position.\n\nOpen: %s' % url, flush=True)
    if args.share:
        print(
            'Friends on the same Wi-Fi: http://%s:%d\nFriends elsewhere: run  cloudflared tunnel --url http://127.0.0.1:%d'
            % (lan_address(), server.server_port, server.server_port),
            flush=True,
        )
    print('\nKeep this window open. Press Ctrl+C to stop.\n', flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nEdge Lab stopped.')
    finally:
        server.server_close()
