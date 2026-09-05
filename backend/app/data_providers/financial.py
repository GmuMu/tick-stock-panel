"""Canonical financial-data contracts and provider-boundary normalization.

Financial amounts are stored as CNY yuan, per-share values as CNY/share, and
ratios as percentage points (``16.75`` means ``16.75%``).  ``period_end`` is
the report period; ``announce_date`` is the first public disclosure date used
by point-in-time backtests.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

import polars as pl

from app.data_providers.normalizer import to_polars
from app.data_providers.schemas import normalize_date, normalize_symbol

FinancialTable = Literal["metrics", "income", "balance_sheet", "cash_flow", "shares"]

FINANCIAL_TABLES: tuple[FinancialTable, ...] = (
    "metrics",
    "income",
    "balance_sheet",
    "cash_flow",
    "shares",
)

FINANCIAL_IDENTITY_COLUMNS = ("symbol", "period_end", "announce_date")

FINANCIAL_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "metrics": (
        *FINANCIAL_IDENTITY_COLUMNS,
        "eps_basic",
        "eps_diluted",
        "bps",
        "ocfps",
        "roe",
        "roe_diluted",
        "roa",
        "gross_margin",
        "net_margin",
        "debt_to_asset_ratio",
        "revenue_yoy",
        "net_income_yoy",
        "operating_cash_to_revenue",
        "inventory_turnover",
    ),
    "income": (
        *FINANCIAL_IDENTITY_COLUMNS,
        "revenue",
        "operating_cost",
        "operating_profit",
        "selling_expense",
        "admin_expense",
        "rd_expense",
        "financial_expense",
        "non_operating_income",
        "non_operating_expense",
        "total_profit",
        "income_tax",
        "net_income",
        "net_income_attributable",
        "net_income_deducted",
        "basic_eps",
        "diluted_eps",
    ),
    "balance_sheet": (
        *FINANCIAL_IDENTITY_COLUMNS,
        "total_assets",
        "total_current_assets",
        "total_non_current_assets",
        "cash_and_equivalents",
        "accounts_receivable",
        "inventory",
        "fixed_assets",
        "intangible_assets",
        "goodwill",
        "total_liabilities",
        "total_current_liabilities",
        "total_non_current_liabilities",
        "short_term_borrowing",
        "long_term_borrowing",
        "accounts_payable",
        "total_equity",
        "equity_attributable",
        "retained_earnings",
        "minority_interest",
    ),
    "cash_flow": (
        *FINANCIAL_IDENTITY_COLUMNS,
        "net_operating_cash_flow",
        "net_investing_cash_flow",
        "net_financing_cash_flow",
        "capex",
        "net_cash_change",
    ),
    "shares": (
        *FINANCIAL_IDENTITY_COLUMNS,
        "total_shares",
        "float_shares",
    ),
}

_COMMON_ALIASES = {
    "ts_code": "symbol",
    "thscode": "symbol",
    "ticker": "symbol",
    "report_period": "period_end",
    "period_end_date": "period_end",
    "end_date": "period_end",
    "report_date": "announce_date",
    "publish_date": "announce_date",
    "announcement_date": "announce_date",
    "report_date_ms": "announce_date",
    "announce_date_ms": "announce_date",
}

_TABLE_ALIASES = {
    "metrics": {
        "eps": "eps_basic",
        "basic_eps": "eps_basic",
        "diluted_eps": "eps_diluted",
        "book_value_per_share": "bps",
        "operating_cash_flow_per_share": "ocfps",
        "return_on_equity": "roe",
        "return_on_assets": "roa",
        "gross_profit_margin": "gross_margin",
        "net_profit_margin": "net_margin",
        "asset_liability_ratio": "debt_to_asset_ratio",
    },
    "income": {
        "operating_income": "revenue",
        "operating_revenue": "revenue",
        "operating_costs": "operating_cost",
        "operating_expense": "operating_cost",
        "sales_fee": "selling_expense",
        "selling_fees": "selling_expense",
        "manage_fee": "admin_expense",
        "management_expense": "admin_expense",
        "research_and_development_expenses": "rd_expense",
        "interest_expenses": "financial_expense",
        "profit_total": "total_profit",
        "income_tax_expense": "income_tax",
        "net_profit": "net_income",
        "parent_holder_net_profit": "net_income_attributable",
        "deducted_net_profit": "net_income_deducted",
    },
    "balance_sheet": {
        "assets_total": "total_assets",
        "total_debt": "total_liabilities",
        "holder_equity_total": "total_equity",
        "cash": "cash_and_equivalents",
        "non_current_nets_total": "total_non_current_assets",
    },
    "cash_flow": {
        "act_cash_flow_net": "net_operating_cash_flow",
        "invest_cash_flow_net": "net_investing_cash_flow",
        "financing_cash_flow_net": "net_financing_cash_flow",
        "pay_fixed_assets_etc_cash": "capex",
        "cash_equivalents_net_addition": "net_cash_change",
    },
    "shares": {
        "total_share_capital": "total_shares",
        "share_capital": "total_shares",
        "circulating_shares": "float_shares",
        "float_share_capital": "float_shares",
    },
}

_DATE_COLUMNS = {"period_end", "announce_date"}


def _finite_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso_date(value: object) -> str | None:
    normalized = normalize_date(value)
    return normalized.isoformat() if normalized is not None else None


def _rows_with_symbol_defaults(data, symbols: Iterable[str] | None) -> pl.DataFrame:
    return to_polars(data)


def _rename_aliases(df: pl.DataFrame, table: str) -> pl.DataFrame:
    aliases = {**_COMMON_ALIASES, **_TABLE_ALIASES.get(table, {})}
    # Never overwrite an already canonical value.  This also avoids duplicate
    # columns when a provider returns both an alias and its canonical name.
    rename = {
        source: target
        for source, target in aliases.items()
        if source in df.columns and target not in df.columns
    }
    return df.rename(rename) if rename else df


def normalize_financial(
    data,
    table: str,
    *,
    source: str = "unknown",
    symbols: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Normalize one provider response into the stable financial table shape.

    Unknown numeric provider fields remain as extension columns.  Identity
    fields and known canonical fields are normalized; invalid identity rows
    are dropped rather than written as ambiguous financial observations.
    """
    if table not in FINANCIAL_TABLES:
        raise ValueError(f"unsupported financial table: {table}")
    df = _rows_with_symbol_defaults(data, symbols)
    if df.is_empty():
        return _empty_frame(table)

    df = _rename_aliases(df, table)
    defaults = [str(value) for value in (symbols or []) if str(value).strip()]
    if "symbol" in df.columns:
        if len(defaults) == 1:
            df = df.with_columns(pl.col("symbol").fill_null(defaults[0]).alias("symbol"))
        df = df.with_columns(
            pl.col("symbol").map_elements(normalize_symbol, return_dtype=pl.Utf8).alias("symbol")
        )
    else:
        symbol = defaults[0] if len(defaults) == 1 else None
        df = df.with_columns(pl.lit(symbol, dtype=pl.Utf8).alias("symbol"))

    for column in _DATE_COLUMNS:
        if column in df.columns:
            df = df.with_columns(
                pl.col(column).map_elements(_iso_date, return_dtype=pl.Utf8).alias(column)
            )
        else:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))

    numeric_columns = set(FINANCIAL_TABLE_COLUMNS[table]) - set(FINANCIAL_IDENTITY_COLUMNS)
    for column in numeric_columns:
        if column in df.columns:
            df = df.with_columns(
                pl.col(column).map_elements(_finite_float, return_dtype=pl.Float64).alias(column)
            )

    df = df.filter(
        pl.col("symbol").is_not_null() & pl.col("period_end").is_not_null()
    )
    if df.is_empty():
        return _empty_frame(table)

    if source and "source" not in df.columns:
        df = df.with_columns(pl.lit(source).alias("source"))

    for column in FINANCIAL_TABLE_COLUMNS[table]:
        if column not in df.columns:
            dtype = pl.Utf8 if column in _DATE_COLUMNS or column == "symbol" else pl.Float64
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(column))

    ordered = [
        *FINANCIAL_TABLE_COLUMNS[table],
        *[column for column in df.columns
          if column not in FINANCIAL_TABLE_COLUMNS[table] and column != "source"],
    ]
    if "source" in df.columns:
        ordered.append("source")
    return df.select([column for column in ordered if column in df.columns])


def _empty_frame(table: str) -> pl.DataFrame:
    schema = {
        column: pl.Utf8 if column in FINANCIAL_IDENTITY_COLUMNS else pl.Float64
        for column in FINANCIAL_TABLE_COLUMNS[table]
    }
    return pl.DataFrame(schema=schema)


def canonical_columns(table: str) -> tuple[str, ...]:
    """Return the stable columns required by one financial dataset."""
    if table not in FINANCIAL_TABLES:
        raise ValueError(f"unsupported financial table: {table}")
    return FINANCIAL_TABLE_COLUMNS[table]


__all__ = [
    "FINANCIAL_IDENTITY_COLUMNS",
    "FINANCIAL_TABLES",
    "FINANCIAL_TABLE_COLUMNS",
    "FinancialTable",
    "canonical_columns",
    "normalize_financial",
]
