# TASK-1005 Position Projection

Status: DONE (2026-09-06)

`position_projection.py` consumes only confirmed paper fills and maintains a
separate `positions` table with quantity, available quantity, average cost,
realized P&L, last fill and revision. Buys remain unavailable until the
explicit T+1 settlement step. The UI reads this projection directly and never
derives holdings from order or journal logs.
