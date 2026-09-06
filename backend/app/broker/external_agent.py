"""Client for a separately deployed line-oriented QMT Agent.

The FastAPI process never imports a vendor SDK. The command is supplied as a
JSON array so subprocess creation never goes through a shell.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from app.broker.protocol import BrokerError


@dataclass(frozen=True)
class ExternalAgentConfig:
    command: tuple[str, ...]
    timeout_seconds: float = 8.0

    @classmethod
    def from_environment(cls) -> ExternalAgentConfig | None:
        raw = os.environ.get("QMT_AGENT_COMMAND", "").strip()
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BrokerError(
                "QMT_AGENT_COMMAND 必须是 JSON 字符串数组",
                code="QMT_AGENT_CONFIG_INVALID",
            ) from exc
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            raise BrokerError(
                "QMT_AGENT_COMMAND 必须是非空字符串数组",
                code="QMT_AGENT_CONFIG_INVALID",
            )
        try:
            timeout = float(os.environ.get("QMT_AGENT_TIMEOUT_SECONDS", "8"))
        except ValueError as exc:
            raise BrokerError(
                "QMT_AGENT_TIMEOUT_SECONDS 必须是数字",
                code="QMT_AGENT_CONFIG_INVALID",
            ) from exc
        if not 0.5 <= timeout <= 60:
            raise BrokerError(
                "QMT_AGENT_TIMEOUT_SECONDS 必须在 0.5 至 60 秒之间",
                code="QMT_AGENT_CONFIG_INVALID",
            )
        return cls(tuple(value), timeout)


class ExternalQmtAgentClient:
    """Synchronous request/response client with a persistent Agent process."""

    def __init__(self, config: ExternalAgentConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.RLock()

    def dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            process = self._ensure_process()
            request_id = uuid.uuid4().hex
            payload = {**command, "id": request_id}
            try:
                assert process.stdin is not None
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
                response = self._responses.get(timeout=self.config.timeout_seconds)
            except queue.Empty as exc:
                self.close()
                raise BrokerError(
                    "QMT Agent 响应超时",
                    code="QMT_AGENT_TIMEOUT",
                ) from exc
            except (BrokenPipeError, OSError) as exc:
                self.close()
                raise BrokerError(
                    "QMT Agent 进程已断开",
                    code="QMT_AGENT_DISCONNECTED",
                ) from exc
            if response.get("id") != request_id:
                self.close()
                raise BrokerError("QMT Agent 响应编号不匹配", code="QMT_AGENT_PROTOCOL_ERROR")
            if not response.get("ok"):
                raise BrokerError(
                    str(response.get("error") or "QMT Agent 执行失败"),
                    code=str(response.get("code") or "QMT_AGENT_ERROR"),
                )
            return response

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
            while not self._responses.empty():
                try:
                    self._responses.get_nowait()
                except queue.Empty:
                    break

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                list(self.config.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=creationflags,
            )
        except (OSError, ValueError) as exc:
            self._process = None
            raise BrokerError(
                "无法启动 QMT Agent",
                code="QMT_AGENT_START_FAILED",
            ) from exc
        assert self._process.stdout is not None
        threading.Thread(
            target=self._read_responses,
            args=(self._process.stdout,),
            name="qmt-agent-reader",
            daemon=True,
        ).start()
        return self._process

    def _read_responses(self, stream: Any) -> None:
        try:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict):
                    self._responses.put(value)
        except (OSError, ValueError):
            return
