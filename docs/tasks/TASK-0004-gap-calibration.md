# TASK-0004 GAP Matrix 与 Development Plan 校准

## Task

- Branch: `audit/0002-reachability`
- Start SHA: `25e5680`
- End SHA: working tree, not committed
- Date: `2026-09-04`
- Scope: 只做 Development Plan V1.0 与当前真实代码入口的校准，不实现业务功能。

## 产物

- `docs/development/GAP_MATRIX_V1.0.md`
- `docs/adr/ADR-0001-plan-runtime-boundary.md`
- 本任务记录

矩阵覆盖 Phase 0-14 的全部计划任务，并为每项记录状态、真实代码入口、前置依赖和下一步。状态使用 `DONE/PARTIAL/GAP/BLOCKED`，避免把现有同名模块误判为计划契约已完成。

## 关键结论

- 当前可开始 `TASK-0101 Canonical Symbol / Date / Unit Contract`。
- `TASK-0102`、`TASK-0103` 已有能力矩阵和路由基础，应在其上补正式契约。
- `TASK-0104` 的统一 `DataQuality/MarketSession` 仍是缺口。
- free-stockdb、Financial-API、Provider Health 和跨源 golden baseline 仍需按依赖顺序建设。
- 交易、OMS、QMT 和小额实盘全部保持 `GAP/BLOCKED`，不得跳过 Risk、Idempotency、Reconcile 和 Kill Switch。

## 验证

- `backend/tests/test_baseline_harness.py` 及受影响回归：`130 passed`
- 新增基线测试 Ruff：通过
- `git diff --check`：通过
- 本任务无前端源码改动，不执行前端构建

## 验收

- AC result: `PASS`
- Next task ready: `YES`，推荐分支 `feat/0101-canonical-contracts`
- 注意：当前工作树仍有未提交的用户/前序任务改动；本任务不自动提交、推送或切换分支。
