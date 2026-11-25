"""Tests for esci_search.core_types (SPEC-00b, SPEC-00.3: T1-T15).

Each test checks one rule. A failing test name should tell you which rule broke.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from esci_search.core_types import GAIN, RankedList, Scored


def make(pairs: list[tuple[str, float]]) -> list[Scored]:
    """Build Scored objects from (product_id, score) pairs, in the given order."""
    return [Scored(pid, score) for pid, score in pairs]


def four_items() -> RankedList:
    """A valid 4-item list used by several tests: B(0.9), A(0.5), C(0.5), D(0.1)."""
    return RankedList.from_scores(7, make([("D", 0.1), ("C", 0.5), ("B", 0.9), ("A", 0.5)]))


# T1
def test_gain_values() -> None:
    assert GAIN == {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}


# T2
def test_gain_is_read_only() -> None:
    with pytest.raises(TypeError):
        GAIN["E"] = 2.0  # type: ignore[index]
    assert GAIN["E"] == 1.0  # and the value really did not change


# T3
@pytest.mark.parametrize(
    "raw",
    [np.float32(0.5), np.float64(0.5), 0.5],
    ids=["numpy_float32", "numpy_float64", "python_float"],
)
def test_scored_converts_numpy_to_float(raw: float) -> None:
    s = Scored("a", raw)
    assert type(s.score) is float  # exactly float, not a numpy subclass
    assert s.score == 0.5


# T3 (extra): an int score becomes a float too (spec table)
def test_scored_converts_int_to_float() -> None:
    s = Scored("a", 3)
    assert type(s.score) is float
    assert s.score == 3.0


# T3 (extra): infinities are allowed (spec table)
@pytest.mark.parametrize("value", [float("inf"), float("-inf")], ids=["inf", "-inf"])
def test_scored_allows_infinity(value: float) -> None:
    assert Scored("a", value).score == value


# T4
@pytest.mark.parametrize(
    ("product_id", "score"),
    [("a", float("nan")), ("", 1.0)],
    ids=["nan_score", "empty_id"],
)
def test_scored_rejects_nan_and_empty_id(product_id: str, score: float) -> None:
    with pytest.raises(ValueError):
        Scored(product_id, score)


# T5
def test_from_scores_sorts_by_score_desc() -> None:
    rl = RankedList.from_scores(1, make([("a", 0.1), ("b", 0.9), ("c", 0.5)]))
    assert rl.product_ids() == ("b", "c", "a")


# T6: catches sorted(..., reverse=True), which would put C before A
def test_ties_broken_by_product_id_asc() -> None:
    rl = RankedList.from_scores(1, make([("B", 0.9), ("C", 0.5), ("A", 0.5), ("D", 0.1)]))
    assert rl.product_ids() == ("B", "A", "C", "D")


# T7: a generator can only be consumed once; from_scores must still work
def test_from_scores_accepts_generator() -> None:
    pairs = [("x", 0.2), ("y", 0.8)]
    rl = RankedList.from_scores(1, (Scored(pid, s) for pid, s in pairs))
    assert rl.product_ids() == ("y", "x")


# T8
def test_empty_is_valid() -> None:
    rl = RankedList.from_scores(1, [])
    assert len(rl) == 0
    assert rl.items == ()
    assert rl.product_ids() == ()


# T9: scores differ, so only the duplicate check (not the order check) can catch this
def test_duplicate_ids_raise() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        RankedList.from_scores(1, make([("a", 0.1), ("a", 0.9)]))


# T10
def test_unsorted_direct_construction_raises() -> None:
    with pytest.raises(ValueError, match="rank order"):
        RankedList(1, (Scored("a", 0.1), Scored("b", 0.9)))


# T10 (extra): equal scores in the wrong id order are also rejected
def test_wrong_tie_order_direct_construction_raises() -> None:
    with pytest.raises(ValueError, match="rank order"):
        RankedList(1, (Scored("C", 0.5), Scored("A", 0.5)))


# T10 (extra): an already-sorted tuple is accepted as-is
def test_sorted_direct_construction_ok() -> None:
    rl = RankedList(1, (Scored("b", 0.9), Scored("a", 0.1)))
    assert rl.product_ids() == ("b", "a")


# T11
def test_list_items_raise() -> None:
    with pytest.raises(TypeError):
        RankedList(1, [Scored("a", 1.0)])  # type: ignore[arg-type]


# T12
def test_frozen() -> None:
    rl = RankedList.from_scores(1, make([("a", 1.0)]))
    with pytest.raises(dataclasses.FrozenInstanceError):
        rl.query_id = 2  # type: ignore[misc]



# T13: top(-1) must raise; items[:-1] would silently drop the last item
def test_top_k() -> None:
    rl = four_items()
    top2 = rl.top(2)
    assert len(top2) == 2
    assert top2.query_id == rl.query_id
    assert top2.product_ids() == ("B", "A")
    assert len(rl.top(10)) == 4
    assert len(rl.top(0)) == 0
    with pytest.raises(ValueError):
        rl.top(-1)


# T14
def test_product_ids_in_order() -> None:
    assert four_items().product_ids() == ("B", "A", "C", "D")


_pairs = st.lists(
    st.tuples(st.text(min_size=1, max_size=8), st.floats(allow_nan=False)),
    max_size=30,
    unique_by=lambda t: t[0],
)


@given(_pairs)
def test_from_scores_property(pairs: list[tuple[str, float]]) -> None:
    rl = RankedList.from_scores(3, make(pairs))

    # every input id comes out exactly once
    assert sorted(rl.product_ids()) == sorted(pid for pid, _ in pairs)

    # adjacent pairs obey the invariant, checked WITHOUT the -score trick
    for a, b in zip(rl.items, rl.items[1:], strict=False):
        assert a.score > b.score or (a.score == b.score and a.product_id < b.product_id)