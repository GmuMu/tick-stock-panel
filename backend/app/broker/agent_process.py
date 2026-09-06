"""Standalone mock Agent process entry point.

Run with ``python -m app.broker.agent_process`` when testing the JSONL process
boundary.  It never loads a vendor SDK and therefore cannot place real orders.
"""
from __future__ import annotations

from app.broker.agent import QmtAgentCore, run_stdio_agent
from app.broker.mock import MockBroker


def main() -> None:
    run_stdio_agent(QmtAgentCore(MockBroker()))


if __name__ == "__main__":
    main()
