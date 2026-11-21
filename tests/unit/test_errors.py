import pytest

from esci_search import errors
from esci_search.errors import (
    EsciError,
    ConfigError,
    DataError,
    IndexBuildError,
    RetrievalError,
    DependencyTimeout,
    LeakageError,
)

SUBCLASSES = [
    ConfigError,
    DataError,
    IndexBuildError,
    RetrievalError,
    DependencyTimeout,
    LeakageError,
]


def test_base_is_exception():
    assert issubclass(EsciError, Exception)


@pytest.mark.parametrize("cls", SUBCLASSES, ids=lambda c: c.__name__)
def test_all_subclasses_of_base(cls):
    assert issubclass(cls, EsciError)


def test_catch_as_base():
    with pytest.raises(EsciError):
        raise DataError("x")


def test_message_preserved():
    assert str(ConfigError("unknown key 'a'")) == "unknown key 'a'"


def test_all_exports():
    assert errors.__all__ == [
        "EsciError",
        "ConfigError",
        "DataError",
        "IndexBuildError",
        "RetrievalError",
        "DependencyTimeout",
        "LeakageError",
    ]


def test_docstrings():
    for name in errors.__all__:
        doc = getattr(errors, name).__doc__
        assert doc and doc.strip(), f"{name} has no docstring"
