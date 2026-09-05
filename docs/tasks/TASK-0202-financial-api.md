# TASK-0202 Financial-API Provider / Dataset

## Task

- Branch: `feat/0101-canonical-contracts` (当前工作树继续开发，未自动提交)
- Scope: 定义财务数据 canonical schema，并让多数据源在 Provider/同步边界统一。
- Rule: 保留公告日用于 point-in-time 回测；缺失财务值保持 `null`，不伪造为 0。

## 实现

- `backend/app/data_providers/financial.py`
  - 新增五张财务表的稳定列集合：`metrics`、`income`、`balance_sheet`、`cash_flow`、`shares`。
  - 统一 `symbol`、`period_end`、`announce_date` identity。
  - 金额统一为 CNY 元，每股值为 CNY/股，比例统一为百分点（`16.75` 表示 `16.75%`）。
  - 统一供应商别名、日期、有限数值和无效 identity 行处理。
  - 缺失 canonical 字段显式输出 `null`；供应商独有数值字段作为扩展列保留。
- `backend/app/plugins/fuyao/provider.py`
  - 扶摇三大报表和 metrics 输出经过 canonical financial contract。
  - 保留扶摇独有字段，指标接口失败时保留基础报告行，不伪造指标值。
- `backend/app/services/financial_sync.py`
  - TickFlow、自定义 HTTP Provider 和扶摇路径统一经过 `normalize_financial`。
  - 统一写入前的来源标记，避免业务层依赖供应商字段名。
- `backend/tests/test_financial_contract.py`
  - 覆盖字段别名、日期时区、数值转换、无效 identity、稳定列集合和自定义 Provider 收口。
- `backend/tests/test_fuyao_financial.py`
  - 更新指标缺失断言：canonical 列存在但值为 `null`。

## 验收

- AC result: `PASS`
- 五张财务表有稳定 canonical schema：`YES`
- 扶摇 Financial Provider 已接入统一 schema：`YES`
- TickFlow/自定义 HTTP 财务源在同步边界统一：`YES`
- 公告日和报告期分离，支持 point-in-time 门控：`YES`
- 缺失值 fail-closed 为 `null`，不填 0：`YES`
- Provider 独有字段可扩展保留：`YES`

## 验证

- `backend/.venv/Scripts/python.exe -m pytest tests/test_financial_contract.py tests/test_fuyao_financial.py tests/test_financial_shares.py tests/test_fundamental_factors.py -q`：`28 passed`
- `backend/.venv/Scripts/python.exe -m ruff check app/data_providers/financial.py app/data_providers/__init__.py tests/test_financial_contract.py app/plugins/fuyao/provider.py`：通过
- `git diff --check`：通过
- 未执行真实财务 API 联调：需要有效的数据源 Key/服务后再做 smoke test。

## 下一任务

`TASK-0203 Provider Health / Retry / Fallback`：集中记录 Provider 健康、失败率、重试、退避和 fallback 事件。
