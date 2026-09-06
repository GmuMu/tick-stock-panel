# TASK-0803 Trade Plan

状态：DONE

Trade plans structure the symbol, direction, entry/stop/target prices,
position percentage, quantity, validity window, candidate provenance and notes.
An optional `thesis_id` links the plan to a research argument; no plan action
creates an order.

入口：`/api/trading-research/plans` and the Trade Plan tab in
`/trading-research`.
