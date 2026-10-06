# Trading-Game

Trading Game for Optiver Interview

A local practice app for trading-interview games: make markets on a partly hidden hand of cards
against three bots, price probabilities under the clock, and get worked feedback on every decision.
Everything runs on your own computer; all money is imaginary.

## Requirements

- Python 3.9 or newer. Nothing else: no packages to install, no internet needed.
- A web browser.

## Run it

```bash
git clone https://github.com/terminatoratot/Trading-Game.git
cd Trading-Game
python3 edge.py
```

(On Windows, use `python edge.py` if `python3` is not found.)

A browser tab opens at <http://127.0.0.1:8765>. For the market-making card game, go to
<http://127.0.0.1:8765/trading>, or click **Trading game** on the home page.

Keep the terminal window open while you play; press `Ctrl+C` there to stop.

Useful options:

| Command | What it does |
|---|---|
| `python3 edge.py --port 8766` | Use another port if 8765 is busy |
| `python3 edge.py --no-browser` | Start without opening a browser tab |
| `python3 edge.py --self-test` | Run the test suite |
| `python3 edge.py --share` | Let other devices on your Wi-Fi join (see below) |

## The trading game

Each round you see a set of cards worth 2 to 14 (J=11, Q=12, K=13, A=14). Some are face up and the
rest face down. When the round ends, the sum of the card values is the market price.

- **Quotes** read *X at Y*: X is the bid (the market maker buys there), Y is the ask (it sells there).
- **Rotational** mode: each round a different player makes the market. **Open outcry**: everyone
  races to shout a quote, and the first valid one makes the market.
- **Trading:** choose a number of units and buy at the ask, sell at the bid, or pass. Longs must be
  affordable from your balance; shorts must be covered against the worst possible outcome.
- **After each round** you report your profit or loss (exact answers only), then see a breakdown of
  what a better play would have been, the worked maths behind fair value, and the fastest mental
  shortcut for it.
- **Difficulty** is mostly about market events: Easy events change which cards can be dealt, Medium
  ones change how the hand settles, and Hard ones add caps, insiders and stacked events. On Hard
  you also keep track of your balance in your head.

The three bots (Cautious, Sharp and Aggressive) only see the face-up cards, the same as you, except
in the Hard event where one bot is told a hidden card.

## The rest of the app

The home page has probability-betting practice modes: Coach (with step-by-step hints), Interview,
Sprint, Targeted practice (built from your past mistakes), a quick-fire Pricing drill, and live
Multiplayer rooms. Your history and statistics are stored in your own browser.

## Playing with friends

- **Same Wi-Fi:** run `python3 edge.py --share`; it prints an address such as
  `http://192.168.1.20:8765` for friends to open.
- **Anywhere:** run `python3 edge.py --share --port 8766`, then in another terminal
  `cloudflared tunnel --url http://127.0.0.1:8766`
  ([cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  is a free download). It prints a public `https://…trycloudflare.com` link. Anyone with the link can
  play while both commands are running, so only share it with people you trust.

Named trading-game results go on a shared 30-day leaderboard, saved in an `edge_lab_data/` folder
next to `edge.py`.

## Project layout

```
edge.py                 starts the app
edge_lab/
  trading.py            the trading game: cards, market events, bots, settlement, worked maths
  probability.py        boards and exact probabilities for the practice modes
  coaching.py           round feedback and bet sizing
  insights.py           finds patterns in your answers for targeted practice
  game.py, rooms.py     practice sessions, the pricing drill and multiplayer rooms
  server.py             the local web server
  static/               the web pages, styles and scripts
  tests/                the test suite
```

## Credits

Maths is typeset with [KaTeX](https://katex.org), bundled in `edge_lab/static/vendor/katex`
under the MIT licence (see `LICENSE.txt` there).
