# TASK-0102 Data Capability Matrix

## Task

- Branch: `feat/0101-canonical-contracts` (当前工作树继续开发，未自动提交)
- Scope: 在现有能力注册表和 `/api/settings/capability-matrix` 上补齐最小能力状态契约。
- Rule: 不建立第二套 Provider 容器，不改变既有 `usable` 门控和数据源路由行为。

## 实现

- `backend/app/data_providers/capabilities.py`
  - 增加 `CapabilityStatus`、`DataCapability`、`CapabilityMatrix` 类型契约。
  - 注册表为每个能力声明稳定 `priority`，数字越小越重要。
  - 能力对象增加 `provider`、`source`、`health`、`status`。
  - `status` 使用 `USABLE` / `DEGRADED` / `UNAVAILABLE`。
  - `health` 使用 `healthy` / `degraded` / `unavailable`。
  - 健康的生效源为 `USABLE`；生效源健康异常，或当前路由不可用但存在候选时为 `DEGRADED`；无候选时为 `UNAVAILABLE`。
  - 保留 `current/effective/usable/candidates/pending` 等旧字段，保持 API 向后兼容。
- `backend/app/api/settings.py`
  - 能力矩阵入口补充注入 `full_minute_data_provider`，避免注册表字段在 API 边界丢失。
- `frontend/src/lib/api.ts`
  - 同步 `CapabilityRoute` 的状态、健康、优先级和生效源类型。
- `frontend/src/components/Layout.tsx`
  - 侧栏能力徽标按 `USABLE` / `DEGRADED` / `UNAVAILABLE` 渲染。
- `frontend/src/pages/settings/DataSources.tsx`
  - 数据源切换的乐观更新同步维护新状态字段，避免切换期间显示旧健康状态。

## 验收

- AC result: `PASS`
- 能力清单可枚举 provider/source/health/priority：`YES`
- 能表达 `UNAVAILABLE/DEGRADED/USABLE`：`YES`
- `usable` 仍是业务能力门控的事实字段：`YES`
- `full_minute` API 路由偏好不丢失：`YES`
- 未读取、输出或持久化真实 API Key：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest tests/test_capability_matrix.py tests/test_capability_augment.py -q`：`24 passed`
- `backend/.venv/Scripts/python.exe -m ruff check app/data_providers/capabilities.py tests/test_capability_matrix.py`：通过
- `tsc -b`：通过
- `vite build`：通过，`2734 modules transformed`，仅有既有大 chunk warning
- `git diff --check`：通过

## 下一任务

`TASK-0103 Capability Router`：统一 fallback provenance，继续保持 Strategy/Backtest 不直接依赖供应商 SDK。
