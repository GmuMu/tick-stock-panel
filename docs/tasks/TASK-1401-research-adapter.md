# TASK-1401 Research Adapter

Status: DONE (2026-09-06)

`backend/app/research/contract.py` defines a vendor-neutral,
versioned `ResearchArtifact` and read-only `ResearchAdapter` protocol. The
contract carries symbol, as-of time, thesis, features, payload, provenance,
and a deterministic fingerprint.

The boundary is intentionally separate from Broker, OMS, and position
projection modules.
