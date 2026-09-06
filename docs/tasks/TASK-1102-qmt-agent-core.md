# TASK-1102 QMT Agent Core

Status: DONE (2026-09-06, isolated mock agent)

`backend/app/broker/agent.py` provides `QmtAgentCore`, a command dispatcher
that can run behind a separate process. `agent_process.py` exposes a
line-oriented JSONL entry point suitable for a Windows QMT worker.

The current agent only hosts `MockBroker`; `vendor_sdk_loaded` is explicitly
false and no QMT SDK is imported. This keeps the FastAPI process independent
from Windows-only vendor runtime behavior.
