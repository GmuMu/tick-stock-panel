# TASK-0605 Alert Delivery

状态：DONE（2026-09-05）

## 实现

- `backend/app/services/alert_delivery.py` 定义独立投递状态合同：`queued/sent/failed/skipped`。
- 每个渠道独立记录 delivery ID、规则 revision、尝试次数、错误原因和更新时间，追加写入 `data/user_data/alert_deliveries.jsonl`。
- SSE、系统通知、飞书和企业微信均走独立投递审计；投递失败不会阻塞告警主记录或 SSE。
- 飞书保留原有业务错误不重试、网络/5xx 退避重试；企业微信补充同样的网络/5xx 重试与 4xx/业务错误不重试。
- 新增 `/api/alerts/deliveries` 诊断查询入口。

## 验收

- `backend/tests/test_alert_delivery.py`
- 覆盖成功、失败、跳过、规则 revision 关联以及企业微信 5xx/4xx 重试边界。
- 监控专项回归：`128 passed`。

## 环境说明

- 前端构建仍受 npm registry 下载阶段的 `EACCES`/网络问题影响，未将前端构建标记为通过。
