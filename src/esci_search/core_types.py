from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

Label = Literal["E", "S", "C", "I"]
GAIN: Final[Mapping[Label, float]] = MappingProxyType({"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0})


@dataclass(frozen=True, slots=True)
class Query:
    query_id: int  # ESCI query_id, e.g. 12345
    text: str  # the query string as typed by the shopper, e.g. "iphone 13 case clear"


@dataclass(frozen=True, slots=True)
class Product:
    product_id: str  # ESCI product_id (an ASIN), e.g. "B07XKZJ8TM"
    title: str  # from product_title; "" if missing
    brand: str | None  # from product_brand; None if missing in the source
    color: str | None  # from product_color; None if missing
    bullets: str | None  # from product_bullet_point; None if missing
    doc_text: str  # the cleaned text used for search (SPEC-01.4); always a str, may be ""


@dataclass(frozen=True, slots=True)
class Scored:
    product_id: str
    score: float

    def __post_init__(self) -> None:
        if not self.product_id:
            raise ValueError("empty product_id")

        object.__setattr__(self, "score", float(self.score))

        if math.isnan(self.score):
            raise ValueError(f"Nan score for product {self.product_id}")


def _rank_key(s: Scored) -> tuple[float, str]:
    return (-s.score, s.product_id)


@dataclass(frozen=True, slots=True)
class RankedList:
    query_id: int
    items: tuple[Scored, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("items must be a tuple")

        if len(set(self.product_ids())) < len(self.items):
            raise ValueError(f"duplicate product_id in RankedList for query {self.query_id}")

        for i in range(len(self.items) - 1):
            if _rank_key(self.items[i]) >= _rank_key(self.items[i + 1]):
                raise ValueError(
                    f"items not in rank order at position {i} for query {self.query_id}"
                )

    @classmethod
    def from_scores(cls, query_id: int, scores: Iterable[Scored]) -> RankedList:
        """Sort scores into rank order and build a RankedList. Duplicates raise ValueError."""
        ordered = sorted(scores, key=_rank_key)
        return cls(query_id, tuple(ordered))

    def __len__(self) -> int:
        """number of items"""
        return len(self.items)

    def product_ids(self) -> tuple[str, ...]:
        """ids in rank order"""
        return tuple(s.product_id for s in self.items)

    def top(self, k: int) -> RankedList:
        """first k items, same query_id"""
        if k < 0:
            raise ValueError(f"k: {k} should not be smaller than zero")
        return RankedList(self.query_id, self.items[:k])
