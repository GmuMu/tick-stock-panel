# TASK-1402 QuantMind Adapter

Status: DONE (2026-09-06, local handoff mode)

`backend/app/research/quantmind.py` provides a local JSON handoff adapter for
QuantMind-shaped research artifacts. It has no network client, no vendor SDK
import, and no trading side effect. The handoff file is stored in
`data/user_data/research/quantmind.json` and is independently backed up with
the runtime data directory.

An actual QuantMind network connector, if required later, must be implemented
behind the same contract and undergo a separate credential and network review.
