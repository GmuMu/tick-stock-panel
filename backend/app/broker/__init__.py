"""Broker/QMT integration boundary.

The package contains protocol-level contracts and a deterministic mock broker.
It deliberately does not import a vendor SDK or place real orders.
"""

from app.broker.protocol import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerError,
    BrokerFill,
    BrokerOrder,
    BrokerStatus,
    OrderRequest,
    QuoteSnapshot,
)

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerError",
    "BrokerFill",
    "BrokerOrder",
    "BrokerStatus",
    "OrderRequest",
    "QuoteSnapshot",
]
