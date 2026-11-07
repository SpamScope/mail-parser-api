import pytest

from mail_parser_api.rate_limit import RateLimiter, client_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_limit_within_sliding_window(clock):
    limiter = RateLimiter(limit=2, window=60, max_keys=10, clock=clock)

    assert limiter.allow("a")
    clock.now += 30
    assert limiter.allow("a")
    assert not limiter.allow("a")
    clock.now += 31
    # The first request left the window; the second is still inside it.
    assert limiter.allow("a")
    assert not limiter.allow("a")


def test_least_recently_used_key_is_evicted_at_cap(clock):
    limiter = RateLimiter(limit=1, window=60, max_keys=2, clock=clock)
    limiter.allow("a")
    limiter.allow("b")
    assert not limiter.allow("a")  # "a" becomes the most recently used

    limiter.allow("c")

    assert len(limiter) == 2
    assert limiter.allow("b")  # "b" was evicted, so it starts afresh
    assert not limiter.allow("c")


def test_expired_keys_are_purged(clock):
    limiter = RateLimiter(limit=1, window=60, max_keys=10, clock=clock)
    limiter.allow("a")
    limiter.allow("b")
    clock.now += 61

    limiter.allow("c")

    assert len(limiter) == 1


@pytest.mark.parametrize(
    ("forwarded_for", "peer", "expected"),
    [
        ("203.0.113.5", "10.0.0.1", "203.0.113.5"),
        ("203.0.113.5, 10.0.0.2", "10.0.0.1", "203.0.113.5"),
        (None, "10.0.0.1", "10.0.0.1"),
        ("2001:db8:1:2:aaaa::1", None, "2001:db8:1:2::/64"),
        ("2001:db8:1:2:bbbb::9", None, "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", None, "2001:db8:1:3::/64"),
        (None, "testclient", "testclient"),
        (None, None, ""),
    ],
)
def test_client_key(forwarded_for, peer, expected):
    assert client_key(forwarded_for, peer) == expected
