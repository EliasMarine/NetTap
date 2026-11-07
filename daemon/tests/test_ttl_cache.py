"""NET-192 PR 3: the LRU + TTL cache behind reverse DNS and WHOIS."""

from services.ttl_cache import TTLCache


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_an_entry_lives_for_its_own_ttl():
    clock = Clock()
    cache = TTLCache(10, clock)
    cache.set("hit", "name", ttl=3600)
    cache.set("miss", None, ttl=300)
    clock.t += 299
    assert cache.get("hit") == "name"
    assert cache.get("miss", "gone") is None
    clock.t += 1
    assert cache.get("miss", "gone") == "gone"
    assert cache.get("hit") == "name"
    clock.t += 3300
    assert cache.get("hit") is None
    assert len(cache) == 0  # expired entries are dropped when read


def test_the_least_recently_used_entry_goes_first():
    cache = TTLCache(2, Clock())
    cache.set("a", 1, ttl=60)
    cache.set("b", 2, ttl=60)
    assert cache.get("a") == 1  # a is now the most recent
    cache.set("c", 3, ttl=60)
    assert cache.get("b") is None
    assert (cache.get("a"), cache.get("c")) == (1, 3)
    assert len(cache) == 2


def test_setting_again_refreshes_the_value_and_ttl():
    clock = Clock()
    cache = TTLCache(2, clock)
    cache.set("a", 1, ttl=10)
    clock.t += 9
    cache.set("a", 2, ttl=10)
    clock.t += 9
    assert cache.get("a") == 2
