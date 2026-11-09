"""NET-228: the Alerts page's category trend compares equal halves of whole slots, or says
there isn't enough data. The old split counted slots, so the partial first and last slots and an
odd count (one more slot in the second half) tilted it towards "increasing"."""

import pytest

from api.alerts import category_trend


def _spark(counts: list[int]) -> dict:
    return {f"2026-11-09T{h:02d}:00:00.000Z": n for h, n in enumerate(counts)}


@pytest.mark.parametrize(
    "counts, expected",
    [
        # partial ends ignored: a busy last (partial) slot is no rise
        ([0, 10, 10, 10, 10, 99], "stable"),
        # a real rise and fall between equal halves
        ([0, 5, 5, 20, 20, 0], "increasing"),
        ([0, 20, 20, 5, 5, 0], "decreasing"),
        # odd count: the oldest whole slot is dropped, halves stay equal (10+10 vs 10+10)
        ([0, 40, 10, 10, 10, 10, 0], "stable"),
        # too few whole slots, too few alerts, or an empty half
        ([0, 50, 50, 0], "not_enough_data"),
        ([0, 2, 3, 4, 5, 0], "not_enough_data"),
        ([0, 0, 0, 30, 30, 0], "not_enough_data"),
        ([], "not_enough_data"),
    ],
)
def test_category_trend(counts, expected):
    assert category_trend(_spark(counts)) == expected


def test_slots_are_read_in_time_order_whatever_the_dict_order():
    spark = _spark([0, 5, 5, 20, 20, 0])
    assert category_trend(dict(reversed(list(spark.items())))) == "increasing"
