"""Market data provider abstraction.

Providers normalize external data sources into the internal parquet schema.
"""
from app.data_providers.base import (
    AssetType,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderRoute,
)
from app.data_providers.financial import (
    FINANCIAL_TABLES,
    canonical_columns,
    normalize_financial,
)
from app.data_providers.health import (
    ProviderHealthRegistry,
    RetryPolicy,
    call_with_retry,
    get_provider_health_registry,
)
from app.data_providers.registry import get_provider

__all__ = [
    "FINANCIAL_TABLES",
    "AssetType",
    "MarketDataProvider",
    "ProviderCapabilities",
    "ProviderHealthRegistry",
    "ProviderRoute",
    "RetryPolicy",
    "call_with_retry",
    "canonical_columns",
    "get_provider",
    "get_provider_health_registry",
    "normalize_financial",
]
