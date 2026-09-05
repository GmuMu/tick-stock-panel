# TASK-0203 Provider Health / Retry / Fallback

## Task

- Branch: `feat/0101-canonical-contracts`
- Scope: 在现有 `ProviderRoute` 路由边界上统一记录 Provider 健康、失败率、重试、退避和 fallback。
- Rule: registry 只保存可序列化运行元数据，不保存 Provider 对象、API Key 或原始响应。

## 实现

- `backend/app/data_providers/health.py`
  - 新增进程级、线程安全的 `ProviderHealthRegistry`，按 `provider + dataset` 聚合调用次数、成功/失败次数、error rate、连续失败、延迟、重试和 fallback。
  - 新增 `RetryPolicy` 与 `call_with_retry`，默认最多 2 次尝试，仅对超时、连接错误、429/5xx 等瞬时错误使用指数退避。
  - 认证错误、权限错误和 Provider 契约错误不做无意义重试。
  - 错误消息限长并脱敏常见 `api_key`、`token`、`authorization`、`secret` 字段。
- `backend/app/services/kline_sync.py`
  - 日 K、除权、分钟、全量分钟和单标的补拉的 Provider 调用统一经过 retry/health 边界。
  - 现有 `ProviderRoute` fallback provenance 同步记录到同一 registry。
- `backend/app/services/financial_sync.py`
  - TickFlow 与自定义财务源调用统一进入 health/retry 记录。
- `backend/app/services/quote_service.py`
  - 自定义实时源、指数补充和 TickFlow 实时请求统一进入 health/retry 记录。
- `backend/app/services/minute_refresh.py`
  - 全量分钟源解析 fallback 复用同一健康事件记录。
- `backend/app/data_providers/capabilities.py`
  - 能力矩阵在不发起网络请求的前提下叠加运行时健康状态。
- `backend/app/api/settings.py`
  - 新增只读 `GET /api/settings/provider-health`，支持按 Provider 和 dataset 过滤并返回汇总 error rate。
- `frontend/src/lib/api.ts`
  - 增加 Provider health API 的 TypeScript 契约。

## 验收

- AC result: `PASS`
- Provider 健康按标准 dataset 聚合：`YES`
- transient retry + exponential backoff：`YES`
- 认证错误不重试：`YES`
- fallback、错误率、延迟和最后错误可观测：`YES`
- API Key 等敏感字段不进入状态输出：`YES`
- Strategy/Backtest 不直接依赖 Provider SDK：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest tests/test_provider_health.py tests/test_capability_matrix.py tests/test_capability_router.py tests/test_minute_routing.py tests/test_fuyao_financial.py tests/test_financial_contract.py -q`：`83 passed`
- `backend/.venv/Scripts/python.exe -m ruff check app/data_providers/health.py app/data_providers/capabilities.py app/data_providers/__init__.py tests/test_provider_health.py`：通过
- `git diff --check`：通过
- 未执行真实网络联调：仍需要有效的扶摇 Key 或运行中的 free-stockdb 服务。

## 下一任务

`TASK-0204 Cross-Provider Golden`：建立跨 Provider fixture，验证字段、单位、复权和报告期口径。
