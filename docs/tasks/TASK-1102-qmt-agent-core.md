# TASK-1102 QMT Agent Core

Status: DONE (2026-09-06, isolated mock agent)

`backend/app/broker/agent.py` provides `QmtAgentCore`, a command dispatcher
that can run behind a separate process. `agent_process.py` exposes a
line-oriented JSONL entry point suitable for a Windows QMT worker.

The default Agent process only hosts `MockBroker`; `vendor_sdk_loaded` is
explicitly false and no QMT SDK is imported by FastAPI. The optional
`qmt_vendor_agent.py` worker owns the vendor import and speaks the same JSONL
boundary when launched with explicit QMT configuration.
