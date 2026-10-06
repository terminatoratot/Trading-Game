"""Shared helpers for the test suite."""


def guess(session, **overrides):
    """A full set of probability estimates (default 50%) for the current board."""
    return dict({e['id']: 50 for e in session.current['events']}, **overrides)
