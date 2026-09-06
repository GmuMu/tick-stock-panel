# TASK-0804 Decision Gate

状态：DONE

Decision gates support `pending`, `approved`, `rejected` and `expired` states,
retain rationale and expiry time, and record every transition with revision and
audit metadata. Expired pending gates are exposed as expired on read. Approval
is a research confirmation only and cannot reach a broker.

入口：`/api/trading-research/decisions` and the Decision Gate tab in
`/trading-research`.
