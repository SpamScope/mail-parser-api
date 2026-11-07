"""In-memory sliding-window rate limiter keyed by client address."""

import ipaddress
import time
from collections import OrderedDict, deque
from collections.abc import Callable

IPV6_PREFIX_LENGTH = 64


def client_key(forwarded_for: str | None, peer: str | None) -> str:
    """Return the rate limit key of a client.

    The first ``X-Forwarded-For`` value wins over the peer address because the
    service runs behind a reverse proxy that sets it. An IPv4 address is used
    whole; an IPv6 address is collapsed to its /64 network, since one host
    usually controls a whole /64.

    Args:
        forwarded_for: Value of the ``X-Forwarded-For`` header, if any.
        peer: Address of the TCP peer, if known.

    Returns:
        The client key. A value that is not an IP address is returned unchanged.

    """
    raw = forwarded_for.split(",")[0].strip() if forwarded_for else peer or ""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if address.version == 6:
        network = ipaddress.ip_network(f"{address}/{IPV6_PREFIX_LENGTH}", strict=False)
        return str(network)
    return str(address)


class RateLimiter:
    """Allow at most ``limit`` requests per ``window`` seconds for each key.

    Keys are kept in least-recently-used order. Expired keys are purged on each
    call and, above ``max_keys``, the least recently used key is evicted, so
    memory stays bounded whatever the number of clients.
    """

    def __init__(
        self,
        limit: int,
        window: float,
        max_keys: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty rate limiter.

        Args:
            limit: Requests allowed per key within the window.
            window: Length of the sliding window in seconds.
            max_keys: Maximum number of keys kept in memory.
            clock: Monotonic time source, replaceable in tests.

        """
        self._limit = limit
        self._window = window
        self._max_keys = max_keys
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        """Return the number of keys currently tracked."""
        return len(self._hits)

    def allow(self, key: str) -> bool:
        """Record a request for ``key`` and tell whether it is within the limit.

        Args:
            key: Client key, see :func:`client_key`.

        Returns:
            True if the request is allowed, False if the limit is exceeded.

        """
        now = self._clock()
        expiry = now - self._window
        hits = self._hits.pop(key, deque())
        while hits and hits[0] <= expiry:
            hits.popleft()
        allowed = len(hits) < self._limit
        if allowed:
            hits.append(now)
        if hits:
            self._hits[key] = hits
        self._purge(expiry)
        return allowed

    def _purge(self, expiry: float) -> None:
        """Drop expired keys from the oldest end and evict above the key cap."""
        while self._hits:
            oldest_hits = next(iter(self._hits.values()))
            if oldest_hits[-1] > expiry and len(self._hits) <= self._max_keys:
                break
            self._hits.popitem(last=False)
