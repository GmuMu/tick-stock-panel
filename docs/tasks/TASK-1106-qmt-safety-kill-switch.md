# TASK-1106 QMT Safety / Kill Switch

Status: DONE (2026-09-06, fail-closed mock boundary)

`backend/app/broker/safety.py` persists the kill switch and execution mode in
the user data directory. It blocks disconnected brokers, active kill switch,
missing HUMAN_CONFIRM approval and AUTO mode. The broker API exposes status,
trip and reset operations, with every runtime action recorded locally.

The default mode is `HUMAN_CONFIRM`; real orders are always disabled in Phase
11. Resetting the kill switch does not enable AUTO or real trading.
