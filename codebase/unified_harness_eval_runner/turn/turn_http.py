#!/usr/bin/env python3
"""Execute one HTTP-mode turn via A2A JSON-RPC."""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from typing import Optional

from server import HarnessError


def run_turn(
    host_port: int,
    config: dict,
    utterance: str,
    turn_count: int,
    session_id: Optional[str],
    timeout: float,
) -> dict:
    """Run one HTTP turn via A2A JSON-RPC."""
    http_server_config = config["http_server"]
    if session_id is None:
        session_id = str(uuid.uuid4())

    endpoint = f"http://localhost:{host_port}{http_server_config.get('path', '/api/v1/a2a')}"
    request_body = {
        "jsonrpc": "2.0",
        "id": turn_count,
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "messageId": str(uuid.uuid4()),
                "taskId": str(uuid.uuid4()),
                "contextId": session_id,
                "role": "user",
                "parts": [{"kind": "text", "text": utterance}],
                "metadata": {
                    "credentialProxyApiUrl": "http://unused.invalid/api",
                    "tenantId": "00000000-0000-0000-0000-000000000000",
                    "correlationId": str(uuid.uuid4()),
                    "serverUrl": f"http://localhost:{http_server_config.get('port', 3000)}",
                    **(
                        {"modelProvider": config["model_provider"]}
                        if config.get("model_provider")
                        else {}
                    ),
                    **(config.get("metadata") or {}),
                },
            },
            "configuration": {"blocking": True, "historyLength": 1},
        },
    }
    started_at = time.monotonic()
    request = urllib.request.Request(
        endpoint,
        json.dumps(request_body).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.load(response)
    except OSError as exc:
        raise HarnessError(f"HTTP turn against {endpoint} failed: {exc}") from exc
    latency_ms = (time.monotonic() - started_at) * 1000

    if reply.get("error"):
        raise HarnessError(f"A2A error from {endpoint}: {reply['error']}")
    result = reply.get("result") or {}
    if result.get("kind") == "message":
        parts = result.get("parts") or []
    else:
        status = result.get("status") or {}
        if status.get("state") not in (None, "completed"):
            raise HarnessError(f"A2A task ended in state {status.get('state')!r}")
        parts = (status.get("message") or {}).get("parts") or []
    answer = (
        "\n".join(
            part.get("text", "") for part in parts if part.get("kind") == "text"
        ).strip()
        or "Done."
    )

    return {
        "answer": answer,
        "session_id": session_id,
        "steps": [],
        "usage": {},
        "skill_calls": [],
        "latency_in_ms": latency_ms,
    }
