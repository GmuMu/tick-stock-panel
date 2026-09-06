# TASK-1202 Human Confirm

Status: DONE (2026-09-06, local/mock verification)

`backend/app/services/human_confirm.py` implements an auditable confirmation
lifecycle: request, approve/reject, expiry, payload hash validation and
one-time consumption. Broker order requests in `HUMAN_CONFIRM` mode must use
an approved confirmation whose action and normalized payload match exactly.

The Broker/QMT page exposes the flow as request confirmation, approve and
submit. Reusing a consumed confirmation or changing order content is rejected
with a structured conflict code.
