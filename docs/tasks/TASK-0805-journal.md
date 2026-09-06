# TASK-0805 Journal

状态：DONE

Journal entries support plan, decision, order, fill, review and note kinds,
with optional plan/decision links, occurred time and structured payload. Order
and fill are reservation fields for later phases, not execution integrations.
The UI also exposes the immutable audit stream as a read-only view.

入口：`/api/trading-research/journal`、`/api/trading-research/audit` and the
Journal/Audit tabs in `/trading-research`.
