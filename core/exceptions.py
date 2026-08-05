"""
Domain / operational exceptions for Safety Gate and structured error handling.
"""

from __future__ import annotations


class AppDomainError(Exception):
    """Base for meaningful, catchable domain errors."""


class DataProviderError(AppDomainError):
    """Upstream market/data provider failed or returned unusable data."""


class InsufficientQuotaError(AppDomainError):
    """User plan / rate limit exhausted for a billed feature."""


class DatabaseNotInitializedError(AppDomainError):
    """initialize_database_connection() was not called before DB access."""
