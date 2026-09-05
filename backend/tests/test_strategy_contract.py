"""Strategy metadata and execution provenance contract tests."""
from __future__ import annotations

import json
from datetime import date

import polars as pl
import pytest

from app.strategy.engine import StrategyDataContext, StrategyEngine


def _strategy_code(
    strategy_id: str,
    *,
    meta_extra: str = "",
    backend: str = "polars_expr",
    body: str = "return pl.lit(True)",
) -> str:
    if backend == "polars_expr":
        implementation = f"""
import polars as pl
def filter(df, params):
    {body}
"""
    else:
        implementation = ""
    return f'''import polars as pl
META = {{
    "id": "{strategy_id}",
    "name": "{strategy_id}",
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    {meta_extra}
}}
EXECUTION_BACKEND = "{backend}"
{implementation}
'''


def _context() -> StrategyDataContext:
    return StrategyDataContext(
        asset_type="stock",
        timeframe="1d",
        as_of=date(2026, 1, 2),
        current=pl.DataFrame({"symbol": ["000001.SZ"]}),
    )


def test_contract_defaults_and_result_provenance_are_serializable(tmp_path):
    path = tmp_path / "demo.py"
    path.write_text(
        _strategy_code(
            "demo",
            meta_extra='"required_features": ["close"], "params": [],',
        ),
        encoding="utf-8",
    )
    engine = StrategyEngine(strategy_dirs=[tmp_path])

    strategy = engine.get("demo")
    assert strategy.contract is not None
    assert strategy.contract.contract_version == "1.0"
    assert strategy.contract.strategy_version == "1.0.0"
    assert strategy.contract.lifecycle == "active"
    assert strategy.contract.required_features == ("close",)

    result = engine.run(
        "demo",
        _context(),
        overrides={"basic_filter": {"enabled": False}},
    )
    payload = {
        "contract_version": result.contract_version,
        "strategy_version": result.strategy_version,
        "provenance": result.provenance,
    }
    json.dumps(payload, ensure_ascii=False)
    assert result.provenance == {
        "contract_version": "1.0",
        "strategy_id": "demo",
        "strategy_version": "1.0.0",
        "source": "custom",
        "execution_backend": "polars_expr",
        "lifecycle": "active",
        "required_features": ["close"],
        "asset_type": "stock",
        "timeframe": "1d",
        "as_of": "2026-01-02",
        "input_features": ["close"],
        "lookback_days": 1,
        "warmup_bars": 1,
    }


def test_contract_normalizes_builtin_ai_composite_and_minute_sources(tmp_path):
    builtin = tmp_path / "builtin"
    ai = tmp_path / "ai"
    composite = tmp_path / "composite"
    minute = tmp_path / "minute"
    for directory in (builtin, ai, composite, minute):
        directory.mkdir()

    (builtin / "builtin_one.py").write_text(
        _strategy_code("builtin_one"), encoding="utf-8"
    )
    (ai / "ai_one.py").write_text(
        _strategy_code("ai_one"), encoding="utf-8"
    )
    (composite / "combo.py").write_text(
        _strategy_code(
            "combo",
            meta_extra=(
                '"children": [{"strategy_id": "builtin_one", "weight": 1.0}], '
                '"execution_backend": "composite",'
            ),
            backend="composite",
        ),
        encoding="utf-8",
    )
    (minute / "minute_one.py").write_text(
        '''META = {
    "id": "minute_one",
    "asset_types": ["stock"],
    "timeframes": ["1m"],
}
EXECUTION_BACKEND = "minute_filter"
def filter_minute_history(df, params):
    return df
''',
        encoding="utf-8",
    )

    engine = StrategyEngine(strategy_dirs=[builtin, ai, composite, minute])
    metadata = {item["id"]: item for item in engine.list_strategies()}

    assert metadata["builtin_one"]["source"] == "builtin"
    assert metadata["ai_one"]["source"] == "ai"
    assert metadata["combo"]["source"] == "composite"
    assert metadata["minute_one"]["execution_backend"] == "minute_filter"
    assert all(item["contract_version"] == "1.0" for item in metadata.values())
    assert all(item["lifecycle"] == "active" for item in metadata.values())


@pytest.mark.parametrize(
    ("name", "meta_extra"),
    [
        ("bad_lifecycle", '"lifecycle": "unknown",'),
        ("bad_version", '"version": "v1",'),
        ("bad_id", '"id": "bad id",'),
    ],
)
def test_invalid_contract_strategy_is_isolated(tmp_path, name, meta_extra):
    (tmp_path / "stable.py").write_text(
        _strategy_code("stable"),
        encoding="utf-8",
    )
    (tmp_path / f"{name}.py").write_text(
        _strategy_code(name, meta_extra=meta_extra),
        encoding="utf-8",
    )

    engine = StrategyEngine(strategy_dirs=[tmp_path])

    assert engine.has("stable")
    assert not engine.has(name)
    assert any(item["file"].endswith(f"{name}.py") for item in engine.load_errors())


def test_invalid_contract_reload_keeps_previous_registry(tmp_path):
    path = tmp_path / "stable.py"
    path.write_text(_strategy_code("stable"), encoding="utf-8")
    engine = StrategyEngine(strategy_dirs=[tmp_path])
    previous = engine.get("stable")

    path.write_text(
        _strategy_code("stable", meta_extra='"version": "bad",'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="strategy reload failed"):
        engine.reload()

    assert engine.get("stable") is previous


def test_manual_strategy_definitions_keep_contract_compatibility():
    from app.strategy.engine import StrategyDef

    strategy = StrategyDef(
        meta={"id": "manual"},
        basic_filter={},
        entry_signals=[],
        exit_signals=[],
        stop_loss=None,
        trailing_stop=None,
        trailing_take_profit_activate=None,
        trailing_take_profit_drawdown=None,
        max_hold_days=None,
        filter_fn=None,
        filter_history_fn=None,
        lookback_days=7,
        source="custom",
    )

    engine = StrategyEngine(strategy_dirs=[])
    engine._strategies["manual"] = strategy
    result = engine.run(
        "manual",
        _context(),
        overrides={"basic_filter": {"enabled": False}},
    )

    assert result.strategy_version == "1.0.0"
    assert result.provenance["lookback_days"] == 7
