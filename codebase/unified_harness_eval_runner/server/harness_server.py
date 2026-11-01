#!/usr/bin/env python3
"""HTTP gateway over agent containers, driven by per-harness config.

One long-lived server process owns N containers, addressed by session id.
Your evaluation runner drives conversations over HTTP:

    POST   /sessions                   -> create session
    POST   /sessions/{id}/ask          -> user utterance
    GET    /sessions/{id}/stats        -> token/cost totals
    POST   /sessions/{id}/abort        -> interrupt turn
    DELETE /sessions/{id}              -> close session
    GET    /sessions                   -> list session ids
    GET    /healthz                    -> liveness
    ANY    /v1/{path}                  -> LLM proxy (litellm)

Run:
    source .env && export AZURE_API_KEY AZURE_API_BASE
    litellm --config litellm_azure_config.yaml --port 4001 &
    python harness_server.py --host 0.0.0.0 --port 8000   # one gateway, all harnesses
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiohttp
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from server import HarnessError
from server.container import HarnessInstance, DEFAULT_PROMPT_TIMEOUT

DEFAULT_MODEL = "claude-opus-4-6"

DEFAULT_LITELLM_PORT = 4001
DEFAULT_SERVER_PORT = 8000


# ── Session registry ──────────────────────────────────────────────────────────


class _Session:
    def __init__(self, instance: HarnessInstance, trial_key: str) -> None:
        self.instance = instance
        self.trial_key = trial_key
        self.lock = asyncio.Lock()


def _new_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "llm_calls": 0,
        "llm_calls_unparsed": 0,
        "llm_latency_ms": 0.0,
    }


class SessionManager:
    """Multi-tenant: any harness under harnesses/ can be requested per session.
    Harness configs are loaded lazily and cached; one gateway serves them all."""

    def __init__(
        self, model: Optional[str], proxy_base: str, default_harness: str = ""
    ) -> None:
        self.model = model
        self.proxy_base = proxy_base
        self.default_harness = default_harness
        self._harness_configs: dict[str, dict] = {}
        self._sessions: dict[str, _Session] = {}
        # Per-trial LLM usage, keyed by the session's trial key. The container
        # authenticates to /v1 with this key, so the proxy can attribute every
        # LLM call to the session that made it.
        self.usage: dict[str, dict] = {}
        self._registry_lock = asyncio.Lock()

    def harness_config(self, harness: str) -> dict:
        config = self._harness_configs.get(harness)
        if config is None:
            harness_yaml = (
                Path(__file__).parent.parent / "harnesses" / harness / "harness.yaml"
            )
            if not harness_yaml.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown harness {harness!r}: {harness_yaml} not found",
                )
            config = yaml.safe_load(harness_yaml.read_text())
            config["_harness_dir"] = str(harness_yaml.parent)
            self._harness_configs[harness] = config
        return config

    async def create(
        self, workspace: Optional[str] = None, harness: Optional[str] = None
    ) -> str:
        harness = harness or self.default_harness
        if not harness:
            raise HTTPException(
                status_code=400,
                detail="no harness given and the gateway has no default",
            )
        config = self.harness_config(harness)
        image = config.get("image")
        if not image:
            raise HTTPException(
                status_code=400,
                detail=f"harness {harness!r} has no 'image' set in its harness.yaml",
            )
        # Session ids (and thus container names) lead with the harness name so
        # docker ps and the logs say which harness a session belongs to.
        session_id = f"{harness}-{uuid.uuid4().hex[:8]}"
        trial_key = uuid.uuid4().hex
        instance = HarnessInstance(
            image,
            harness_config=config,
            model=self.model,
            workspace=workspace,
            name=f"harness-{session_id}",
            proxy_base=self.proxy_base,
            api_key=trial_key,
        )
        async with self._registry_lock:
            self.usage[trial_key] = _new_usage()
        try:
            await asyncio.to_thread(instance.open)
        except Exception:
            await asyncio.to_thread(instance.close)
            async with self._registry_lock:
                self.usage.pop(trial_key, None)
            raise
        async with self._registry_lock:
            self._sessions[session_id] = _Session(instance, trial_key)
        return session_id

    def get(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"unknown session {session_id!r}"
            )
        return session

    async def close(self, session_id: str) -> dict:
        async with self._registry_lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"unknown session {session_id!r}"
            )
        post_run_result = await asyncio.to_thread(session.instance.close)
        async with self._registry_lock:
            usage = self.usage.pop(session.trial_key, _new_usage())
        if post_run_result:
            for key in (
                "input_tokens",
                "output_tokens",
                "cached_tokens",
                "total_tokens",
            ):
                usage[key] += post_run_result.get(key, 0)
            usage["post_run"] = post_run_result
        return usage

    async def close_all(self) -> None:
        async with self._registry_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self.usage.clear()
        await asyncio.gather(
            *(asyncio.to_thread(session.instance.close) for session in sessions),
            return_exceptions=True,
        )

    def ids(self) -> list[str]:
        return list(self._sessions.keys())


# ── Usage extraction ───────────────────────────────────────────────────────────


def _usage_from_obj(obj) -> Optional[dict]:
    """Normalize a usage block to input/output/cached/total tokens. Handles
    chat completions ("usage"), Responses API ("response".usage) and Anthropic
    messages, including streams that nest it under "message".usage."""
    if not isinstance(obj, dict):
        return None
    usage_data = obj.get("usage")
    for container_key in ("response", "message"):
        if not isinstance(usage_data, dict):
            inner = obj.get(container_key)
            usage_data = inner.get("usage") if isinstance(inner, dict) else None
    if not isinstance(usage_data, dict):
        return None
    details = (
        usage_data.get("prompt_tokens_details")
        or usage_data.get("input_tokens_details")
        or {}
    )
    cache_read = (details.get("cached_tokens") or 0) or (
        usage_data.get("cache_read_input_tokens") or 0
    )
    cache_creation = usage_data.get("cache_creation_input_tokens") or 0
    input_tokens = (
        usage_data.get("prompt_tokens") or usage_data.get("input_tokens") or 0
    )
    if (
        "prompt_tokens" not in usage_data
        and "input_tokens" in usage_data
        and "input_tokens_details" not in usage_data
    ):
        # Anthropic input_tokens excludes cache reads/writes; OpenAI prompt_tokens
        # and Responses-API input_tokens (with input_tokens_details) include them.
        input_tokens += cache_read + cache_creation
    output_tokens = (
        usage_data.get("completion_tokens") or usage_data.get("output_tokens") or 0
    )
    total = usage_data.get("total_tokens") or 0
    if not (input_tokens or output_tokens or total):
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cache_read,
        "total_tokens": max(total, input_tokens + output_tokens),
        "cost_usd": float(usage_data.get("cost") or 0.0),
    }


def _extract_usage(content_type: str, body: bytes) -> Optional[dict]:
    """Pull token usage out of a proxied LLM response body, JSON or SSE."""
    if "text/event-stream" not in content_type:
        try:
            return _usage_from_obj(json.loads(body))
        except (ValueError, UnicodeDecodeError):
            return None
    # SSE: usage may be split across events (Anthropic puts input_tokens in
    # message_start and output_tokens in the final message_delta), so merge
    # by max per field rather than taking any single chunk.
    found = None
    for line in body.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            continue
        try:
            usage_chunk = _usage_from_obj(json.loads(payload))
        except (ValueError, UnicodeDecodeError):
            continue
        if usage_chunk is None:
            continue
        if found is None:
            found = usage_chunk
        else:
            for key in ("input_tokens", "output_tokens", "cached_tokens", "cost_usd"):
                found[key] = max(found[key], usage_chunk[key])
            found["total_tokens"] = max(
                found["total_tokens"],
                usage_chunk["total_tokens"],
                found["input_tokens"] + found["output_tokens"],
            )
    return found


# ── Request/response models ─────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    workspace: Optional[str] = None
    harness: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str


class AskRequest(BaseModel):
    utterance: str
    timeout: float = DEFAULT_PROMPT_TIMEOUT


class AskResponse(BaseModel):
    answer: str
    steps: list = []
    usage: dict = {}
    skill_calls: list = []
    latency_in_ms: Optional[float] = None


# ── App factory ────────────────────────────────────────────────────────────────


def create_app(
    model: Optional[str] = None,
    litellm_port: int = DEFAULT_LITELLM_PORT,
    self_port: int = DEFAULT_SERVER_PORT,
    default_harness: str = "",
) -> FastAPI:
    proxy_base = f"http://host.docker.internal:{self_port}"
    manager = SessionManager(
        model=model, proxy_base=proxy_base, default_harness=default_harness
    )
    real_api_key = os.environ.get("AZURE_API_KEY", "")
    litellm_base = f"http://localhost:{litellm_port}"

    http_session: dict = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        http_session["client"] = aiohttp.ClientSession()
        try:
            yield
        finally:
            await http_session["client"].close()
            await manager.close_all()

    app = FastAPI(title="harness-gateway", lifespan=lifespan)

    # ── LLM proxy (containers point OPENAI_BASE_URL / models.json here) ──────

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def llm_proxy(path: str, request: Request) -> Response:
        # The caller's Bearer token is its trial key — read it before we
        # overwrite the header with the real credential.
        caller_key = request.headers.get("authorization", "")
        caller_key = caller_key[7:] if caller_key.startswith("Bearer ") else caller_key
        if not caller_key:
            caller_key = request.headers.get("x-api-key", "")
        skip_headers = {"host", "content-length", "transfer-encoding", "connection"}
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in skip_headers
        }
        headers["Authorization"] = f"Bearer {real_api_key}"
        body = await request.body()
        target = f"{litellm_base}/v1/{path}"
        started = time.monotonic()
        http_client = http_session["client"]
        async with http_client.request(
            request.method, target, headers=headers, data=body
        ) as upstream_response:
            content_type = upstream_response.headers.get("content-type", "")
            response_body = await upstream_response.read()
            status = upstream_response.status
            response_headers = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower() not in {"transfer-encoding", "content-encoding"}
            }
        elapsed_ms = (time.monotonic() - started) * 1000.0
        accumulator = manager.usage.get(caller_key)
        if accumulator is not None and status < 400:
            usage = _extract_usage(content_type, response_body)
            if usage:
                accumulator["input_tokens"] += usage["input_tokens"]
                accumulator["output_tokens"] += usage["output_tokens"]
                accumulator["cached_tokens"] += usage["cached_tokens"]
                accumulator["total_tokens"] += usage["total_tokens"]
                accumulator["cost_usd"] += usage["cost_usd"]
                accumulator["llm_calls"] += 1
                accumulator["llm_latency_ms"] += elapsed_ms
            elif request.method == "POST":
                accumulator["llm_calls_unparsed"] += 1
                accumulator["llm_latency_ms"] += elapsed_ms
        if "text/event-stream" in content_type:
            return StreamingResponse(
                iter([response_body]),
                status_code=status,
                media_type="text/event-stream",
            )
        return Response(
            content=response_body, status_code=status, headers=response_headers
        )

    # ── Session routes ────────────────────────────────────────────────────────

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "ok": True,
            "mode": "multi-tenant",
            "sessions": len(manager.ids()),
            "model": model or DEFAULT_MODEL,
        }

    @app.get("/sessions")
    async def list_sessions() -> dict:
        return {"sessions": manager.ids()}

    @app.post("/sessions", response_model=CreateSessionResponse)
    async def create_session(
        request_body: CreateSessionRequest,
    ) -> CreateSessionResponse:
        session_id = await manager.create(
            workspace=request_body.workspace, harness=request_body.harness
        )
        return CreateSessionResponse(session_id=session_id)

    @app.post("/sessions/{session_id}/ask", response_model=AskResponse)
    async def ask(session_id: str, request_body: AskRequest) -> AskResponse:
        session = manager.get(session_id)
        async with session.lock:
            try:
                result = await asyncio.to_thread(
                    session.instance.ask_detailed,
                    request_body.utterance,
                    request_body.timeout,
                )
            except HarnessError as exc:
                raise HTTPException(status_code=502, detail=str(exc))
        return AskResponse(**result)

    @app.get("/sessions/{session_id}/stats")
    async def stats(session_id: str) -> dict:
        session = manager.get(session_id)
        return await asyncio.to_thread(session.instance.stats)

    @app.post("/sessions/{session_id}/abort")
    async def abort(session_id: str) -> dict:
        session = manager.get(session_id)
        await asyncio.to_thread(session.instance.abort)
        return {"aborted": True}

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        usage = await manager.close(session_id)
        return {"closed": session_id, "usage": usage}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HTTP gateway over a pool of harness containers."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Global runner config (default: runner_config.yaml); "
        "its harness.name/model are used unless flags override",
    )
    parser.add_argument(
        "--harness",
        default=None,
        help="Default harness for sessions that don't name one "
        "(any harnesses/ subdirectory can be requested per session)",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    parser.add_argument(
        "--litellm-port",
        type=int,
        default=None,
        help="Port the local litellm sidecar listens on "
        "(default: server.litellm_port from the runner config)",
    )
    parser.add_argument(
        "--model", default=None, help="Model name forwarded to harness CLI"
    )
    args = parser.parse_args()

    from config import load_experiment

    experiment = load_experiment(args.config)
    default_harness = args.harness or (
        experiment.harnesses[0] if experiment.harnesses else ""
    )
    model = args.model or experiment.model or DEFAULT_MODEL
    litellm_port = (
        args.litellm_port
        if args.litellm_port is not None
        else experiment.server.litellm_port
    )

    if "AZURE_API_KEY" not in os.environ:
        parser.error("AZURE_API_KEY is not set in the environment")

    import uvicorn

    uvicorn.run(
        create_app(
            model=model,
            litellm_port=litellm_port,
            self_port=args.port,
            default_harness=default_harness,
        ),
        host=args.host,
        port=args.port,
        # Agent turns and inter-turn gaps run far longer than the 5s default, so
        # keep idle connections open long enough to avoid keep-alive reset races.
        timeout_keep_alive=600,
    )


if __name__ == "__main__":
    main()
