__all__ = [
    "EsciError",
    "ConfigError",
    "DataError",
    "IndexBuildError",
    "RetrievalError",
    "DependencyTimeout",
    "LeakageError",
]


class EsciError(Exception):
    """base class for every error this project raises on purpose"""

    pass


class ConfigError(EsciError):
    """a config file or setting is invalid"""

    pass


class DataError(EsciError):
    """input data is missing, corrupt, or fails validation"""

    pass


class IndexBuildError(EsciError):
    """building or loading an index failed"""

    pass


class RetrievalError(EsciError):
    """a retriever or reranker cannot produce a result"""

    pass


class DependencyTimeout(EsciError):
    """an external dependency (Postgres, DynamoDB, Bedrock) did not answer in time"""

    pass


class LeakageError(EsciError):
    """code tried to touch the test split outside the final"""

    pass
