"""Exception hierarchy for esci_search."""

__all__ = [  # noqa: RUF022 - order is base class first, per spec
    "EsciError",
    "ConfigError",
    "DataError",
    "IndexBuildError",
    "RetrievalError",
    "DependencyTimeout",
    "LeakageError",
]


class EsciError(Exception):
    """Raised when base class for every error this project raises on purpose."""


class ConfigError(EsciError):
    """Raised when a config file or setting is invalid."""


class DataError(EsciError):
    """Raised when input data is missing, corrupt, or fails validation."""


class IndexBuildError(EsciError):
    """Raised when building or loading an index failed."""


class RetrievalError(EsciError):
    """Raised when a retriever or reranker cannot produce a result."""


class DependencyTimeout(EsciError):
    """Raised when an external dependency did not answer in time

    Covers Postgres, DynamoDB, Bedrock
    """


class LeakageError(EsciError):
    """Raised when code accesses the test split outside the final evaluation."""
