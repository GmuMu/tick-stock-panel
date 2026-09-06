# TASK-1002 Risk Rules

Status: DONE (2026-09-06)

The default rules cover approved Decision Gate, executable plan state,
price/stop/target relationships, position percentage, A-share lot size, FRESH
quote quality, continuous market session, plan expiry, exposure, price limits,
and available position for sells. Price limits reuse the versioned
`price_limits.py` contract. No unavailable input is guessed.
