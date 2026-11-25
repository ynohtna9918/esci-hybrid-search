"""Tests for esci_search.errors (SPEC-00b, SPEC-00.4: E1-E6)."""

from __future__ import annotations

import pytest

from esci_search import errors
from esci_search.errors import (
    ConfigError,
    DataError,
    DependencyTimeout,
    EsciError,
    IndexBuildError,
    LeakageError,
    RetrievalError,
)

SUBCLASSES = [
    ConfigError,
    DataError,
    IndexBuildError,
    RetrievalError,
    DependencyTimeout,
    LeakageError,
]

EXPECTED_ALL = [
    "EsciError",
    "ConfigError",
    "DataError",
    "IndexBuildError",
    "RetrievalError",
    "DependencyTimeout",
    "LeakageError",
]


# E1
def test_base_is_exception() -> None:
    assert issubclass(EsciError, Exception)


# E2
@pytest.mark.parametrize("cls", SUBCLASSES, ids=lambda c: c.__name__)
def test_all_subclasses_of_base(cls: type[Exception]) -> None:
    assert issubclass(cls, EsciError)


# E2 (extra): DependencyTimeout must NOT also be the built-in TimeoutError (SPEC-00.4 rules)
def test_dependency_timeout_is_not_builtin_timeout() -> None:
    assert not issubclass(DependencyTimeout, TimeoutError)


# E3
def test_catch_as_base() -> None:
    with pytest.raises(EsciError):
        raise DataError("x")


# E4
def test_message_preserved() -> None:
    assert str(ConfigError("unknown key 'a'")) == "unknown key 'a'"


# E5: ruff rule RUF022 requires __all__ to be sorted alphabetically
def test_all_exports() -> None:
    assert list(errors.__all__) == sorted(EXPECTED_ALL)


# E6
@pytest.mark.parametrize("name", EXPECTED_ALL)
def test_docstrings(name: str) -> None:
    doc = getattr(errors, name).__doc__
    assert doc is not None
    assert doc.strip() != ""
