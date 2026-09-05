from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest

from app.services.eod_runner import run_eod_seeds
from app.services.eod_seeds import EODSeedStore, EODSeedStoreError
from app.api.strategy import (
    StrategyCodeSaveRequest,
    StrategyLifecycleRequest,
    StrategyRollbackRequest,
    StrategyCopyRequest,
    _save_strategy_code,
    copy_strategy,
    get_strategy_lifecycle,
    list_eod_seeds,
    list_strategy_revisions,
    rollback_strategy,
    update_strategy_lifecycle,
)
from app.strategy.candidates import batch_from_result, candidate_id
from app.strategy.engine import StrategyResult
from app.strategy.lifecycle import StrategyLifecycleError, StrategyLifecycleStore


def _result() -> StrategyResult:
    return StrategyResult(
        as_of=date(2026, 8, 28),
        strategy_id="custom_demo",
        rows=[
            {"symbol": "000002.SZ", "close": 12.0},
            {"symbol": "000001.SZ", "close": 10.0},
        ],
        total=2,
        scores={"000001.SZ": 90.0, "000002.SZ": 80.0},
        entry_signal_hits=[
            {"symbol": "000001.SZ", "signals": ["signal_buy"]},
        ],
        strategy_version="2.1.0",
        provenance={"source": "custom", "execution_backend": "polars_expr"},
    )


def test_candidate_batch_has_stable_rank_ids_and_provenance():
    batch = batch_from_result(_result())

    assert [item.symbol for item in batch.candidates] == ["000001.SZ", "000002.SZ"]
    assert [item.rank for item in batch.candidates] == [1, 2]
    assert batch.candidates[0].candidate_id == candidate_id(
        "custom_demo", "2026-08-28", "000001.SZ"
    )
    assert batch.candidates[0].signals == ("signal_buy",)
    assert batch.seed_id


def test_eod_seed_store_is_idempotent_and_conflict_safe(tmp_path):
    store = EODSeedStore(tmp_path)
    batch = batch_from_result(_result())
    first = store.put(batch)
    second = store.put(batch)

    assert first == second
    assert store.latest("custom_demo")["seed_id"] == batch.seed_id

    changed = type(batch)(
        model_version=batch.model_version,
        strategy_id=batch.strategy_id,
        as_of=batch.as_of,
        candidates=tuple(),
        provenance=batch.provenance,
        data_quality=batch.data_quality,
        seed_id=batch.seed_id,
    )
    with pytest.raises(EODSeedStoreError, match="冲突"):
        store.put(changed)


def test_lifecycle_store_enforces_transitions_and_keeps_history(tmp_path):
    store = StrategyLifecycleStore(tmp_path)
    assert store.register("custom_demo", "active")["state"] == "active"

    disabled = store.transition("custom_demo", "disabled", reason="test")
    assert disabled["state"] == "disabled"
    assert disabled["history"][-1]["to"] == "disabled"
    assert store.transition("custom_demo", "active")["state"] == "active"

    with pytest.raises(StrategyLifecycleError, match="不允许"):
        store.transition("custom_demo", "draft")


def test_source_revision_snapshots_support_rollback_content(tmp_path):
    store = StrategyLifecycleStore(tmp_path)
    first = store.snapshot_source("custom_demo", "VERSION = 1")
    second = store.snapshot_source("custom_demo", "VERSION = 2")

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert store.read_source_revision("custom_demo", 1) == "VERSION = 1"
    assert [item["revision"] for item in store.list_source_revisions("custom_demo")] == [2, 1]


def test_eod_runner_only_runs_active_strategies(monkeypatch, tmp_path):
    from app.services import eod_runner

    class FakeScreener:
        def __init__(self, repo, asset_type="stock"):
            self.repo = repo
            self.asset_type = asset_type

        def latest_date(self):
            return date(2026, 8, 28)

        def build_strategy_context(self, engine, as_of, strategy_ids, **kwargs):
            return SimpleNamespace(
                as_of=as_of,
                asset_type="stock",
                timeframe="1d",
                current=pl.DataFrame({"symbol": ["000001.SZ"]}),
                history=None,
                market=None,
            )

    class FakeEngine:
        def list_strategies(self, include_research=False):
            return [
                {"id": "active_one", "lifecycle": "active", "asset_types": ["stock"], "timeframes": ["1d"]},
                {"id": "disabled_one", "lifecycle": "disabled", "asset_types": ["stock"], "timeframes": ["1d"]},
            ]

        def run_all(self, context, **kwargs):
            return {"active_one": StrategyResult(as_of=context.as_of, strategy_id="active_one")}

    monkeypatch.setattr(eod_runner, "ScreenerService", FakeScreener)
    result = run_eod_seeds(SimpleNamespace(), FakeEngine(), tmp_path)

    assert result["strategies"] == 1
    assert result["seeds"] == 1
    assert EODSeedStore(tmp_path).latest("active_one") is not None
    assert EODSeedStore(tmp_path).latest("disabled_one") is None


def _strategy_code(strategy_id: str, name: str = "测试策略") -> str:
    return f'''import polars as pl
META = {{
    "id": "{strategy_id}",
    "name": "{name}",
    "asset_types": ["stock"],
    "timeframes": ["1d"],
}}
def filter(df, params):
    return pl.lit(True)
'''


def _api_request(tmp_path, engine):
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(repo=repo, strategy_engine=engine)
        )
    )


def test_strategy_api_revisions_copy_and_rollback_use_current_source(tmp_path):
    custom_dir = tmp_path / "strategies" / "custom"
    custom_dir.mkdir(parents=True)
    engine = __import__("app.strategy.engine", fromlist=["StrategyEngine"]).StrategyEngine(
        strategy_dirs=[custom_dir],
        lifecycle_store=StrategyLifecycleStore(tmp_path),
    )
    request = _api_request(tmp_path, engine)

    _save_strategy_code(
        StrategyCodeSaveRequest(
            strategy_id="custom_revision",
            target_source="custom",
            mode="create",
            code=_strategy_code("wrong", "版本一"),
        ),
        request,
    )
    _save_strategy_code(
        StrategyCodeSaveRequest(
            strategy_id="custom_revision",
            target_source="custom",
            mode="update",
            code=_strategy_code("custom_revision", "版本二"),
        ),
        request,
    )

    revisions = list_strategy_revisions("custom_revision", request)
    assert [item["revision"] for item in revisions["revisions"]] == [2, 1]
    assert '"name": "版本二"' in StrategyLifecycleStore(tmp_path).read_source_revision(
        "custom_revision", 2
    )

    copied = copy_strategy(
        StrategyCopyRequest(
            strategy_id="custom_revision",
            new_strategy_id="custom_copy",
            target_source="custom",
            name="复制策略",
        ),
        request,
    )
    assert copied["ok"] is True
    assert engine.get("custom_copy").source == "custom"
    assert '"id": "custom_copy"' in (
        tmp_path / "strategies" / "custom" / "custom_copy.py"
    ).read_text(encoding="utf-8")

    rolled = rollback_strategy(
        "custom_revision", StrategyRollbackRequest(revision=1), request
    )
    assert rolled["ok"] is True
    assert '"name": "版本一"' in (
        tmp_path / "strategies" / "custom" / "custom_revision.py"
    ).read_text(encoding="utf-8")
    assert rolled["current_revision"] == 3


def test_strategy_api_lifecycle_disables_execution_and_keeps_history(tmp_path):
    custom_dir = tmp_path / "strategies" / "custom"
    custom_dir.mkdir(parents=True)
    path = custom_dir / "custom_lifecycle.py"
    path.write_text(_strategy_code("custom_lifecycle"), encoding="utf-8")
    lifecycle = StrategyLifecycleStore(tmp_path)
    from app.strategy.engine import StrategyEngine

    engine = StrategyEngine(strategy_dirs=[custom_dir], lifecycle_store=lifecycle)
    request = _api_request(tmp_path, engine)

    updated = update_strategy_lifecycle(
        "custom_lifecycle",
        StrategyLifecycleRequest(state="disabled", reason="暂停测试"),
        request,
    )
    assert updated["state"] == "disabled"
    assert get_strategy_lifecycle("custom_lifecycle", request)["history"][-1]["reason"] == "暂停测试"

    with pytest.raises(ValueError, match="only active"):
        engine.run(
            "custom_lifecycle",
            __import__("app.strategy.engine", fromlist=["StrategyDataContext"]).StrategyDataContext(
                asset_type="stock",
                timeframe="1d",
                as_of=date(2026, 8, 28),
                current=pl.DataFrame({"symbol": ["000001.SZ"]}),
            ),
        )

    resumed = update_strategy_lifecycle(
        "custom_lifecycle",
        StrategyLifecycleRequest(state="active"),
        request,
    )
    assert resumed["state"] == "active"
    assert len(get_strategy_lifecycle("custom_lifecycle", request)["history"]) == 2


def test_strategy_api_failed_rollback_restores_file_and_registry(tmp_path):
    custom_dir = tmp_path / "strategies" / "custom"
    custom_dir.mkdir(parents=True)
    path = custom_dir / "custom_safe.py"
    current = _strategy_code("custom_safe", "当前版本")
    path.write_text(current, encoding="utf-8")
    lifecycle = StrategyLifecycleStore(tmp_path)
    lifecycle.register("custom_safe")
    lifecycle.snapshot_source("custom_safe", current)
    lifecycle.snapshot_source("custom_safe", "not valid python (")
    from app.strategy.engine import StrategyEngine

    engine = StrategyEngine(strategy_dirs=[custom_dir], lifecycle_store=lifecycle)
    request = _api_request(tmp_path, engine)

    with pytest.raises(Exception) as exc_info:
        rollback_strategy("custom_safe", StrategyRollbackRequest(revision=2), request)
    assert getattr(exc_info.value, "status_code", None) == 400
    assert path.read_text(encoding="utf-8") == current
    assert engine.get("custom_safe")


def test_strategy_seed_api_lists_filtered_seeds_and_runs_eod(monkeypatch, tmp_path):
    from app.strategy.engine import StrategyEngine

    custom_dir = tmp_path / "strategies" / "custom"
    custom_dir.mkdir(parents=True)
    path = custom_dir / "custom_seed.py"
    path.write_text(_strategy_code("custom_seed"), encoding="utf-8")
    engine = StrategyEngine(strategy_dirs=[custom_dir], lifecycle_store=StrategyLifecycleStore(tmp_path))
    request = _api_request(tmp_path, engine)
    batch = batch_from_result(
        StrategyResult(as_of=date(2026, 8, 28), strategy_id="custom_seed")
    )
    EODSeedStore(tmp_path).put(batch)

    assert len(list_eod_seeds(request)["items"]) == 1
    assert len(list_eod_seeds(request, as_of=date(2026, 8, 28))["items"]) == 1

    expected = {"strategies": 1, "seeds": 1, "candidates": 0}
    monkeypatch.setattr(
        "app.services.eod_runner.run_eod_seeds",
        lambda *args, **kwargs: {**expected, "as_of": "2026-08-28"},
    )
    from app.api.strategy import run_eod_seed_job

    assert run_eod_seed_job(request, as_of=date(2026, 8, 28)) == {
        **expected,
        "as_of": "2026-08-28",
    }
