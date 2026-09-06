# TASK-0802 Thesis

状态：DONE

The trading research API stores a symbol, direction, hypothesis, evidence,
counter-evidence, status and versioned revisions. Repeated writes are
idempotent and stale updates fail closed with HTTP 409.

入口：`/api/trading-research/theses` and the Thesis tab in `/trading-research`.
