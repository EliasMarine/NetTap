"""A bounded LRU cache whose entries expire (NET-192 PR 3: reverse DNS and WHOIS answers).

Not thread-safe: the lookup routes use it from the request loop only.
"""

import time
from collections import OrderedDict
from typing import Any, Callable


class TTLCache:
    """At most `maxsize` entries, least recently used out first; each lives for the ttl it was set with."""

    def __init__(
        self, maxsize: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.maxsize = maxsize
        self._clock = clock
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, default: Any = None) -> Any:
        entry = self._data.get(key)
        if entry is None or entry[0] <= self._clock():
            self._data.pop(key, None)
            self.misses += 1
            return default
        self._data.move_to_end(key)
        self.hits += 1
        return entry[1]

    def set(self, key: Any, value: Any, ttl: float) -> None:
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
