"""Conversation runner: drive agent conversations via Docker container HTTP server."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiohttp

from config import ServerConfig, UserProxyConfig, silence_litellm
from config import TestCaseCriteria, parse_test_case
from run.trace import save_trace, load_trace_from_server_turns


@dataclass
class TrialResult:
    trial_id: int
    sample_id: str
    run_id: str
    thread_id: Optional[str] = None
    status: str = "success"
    error: Optional[str] = None
    total_turns: int = 0
    case_dir: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "trial_id": self.trial_id,
            "sample_id": self.sample_id,
            "run_id": self.run_id,
            "status": self.status,
            "total_turns": self.total_turns,
            "case_dir": self.case_dir,
        }
        if self.usage is not None:
            out["usage"] = self.usage
        if self.error is not None:
            out["error"] = self.error
        return out
from run.user_proxy import UserProxy
from agent_inspect.models.user_proxy.chat import (
    ChatHistory,
    ConversationTurn,
    ResponseFromAgent,
)

logger = logging.getLogger("experiment_runner.conversation")
silence_litellm()


# ── HTTP session management ────────────────────────────────────────────────


async def create_session(
    server_url: str,
    http: aiohttp.ClientSession,
    workspace: str | None = None,
    harness: str | None = None,
) -> str:
    body: dict = {}
    if workspace:
        body["workspace"] = workspace
    if harness:
        body["harness"] = harness
    async with http.post(f"{server_url}/sessions", json=body) as response:
        response.raise_for_status()
        data = await response.json()
    session_id = data["session_id"]
    logger.info(
        "[server] session created: %s (workspace=%s)", session_id, workspace or "none"
    )
    return session_id


async def send_turn(
    server_url: str,
    http: aiohttp.ClientSession,
    session_id: str,
    message: str,
    timeout: float = 600.0,
) -> dict:
    payload = {"utterance": message, "timeout": timeout}
    async with http.post(
        f"{server_url}/sessions/{session_id}/ask",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=timeout + 30),
    ) as response:
        if response.status == 502:
            body = await response.json()
            raise RuntimeError(f"Agent error: {body.get('detail', response.status)}")
        response.raise_for_status()
        return await response.json()


async def delete_session(
    server_url: str,
    http: aiohttp.ClientSession,
    session_id: str,
) -> dict:
    """Close the session; the response body carries its accumulated LLM usage."""
    try:
        async with http.delete(f"{server_url}/sessions/{session_id}") as response:
            response.raise_for_status()
            return await response.json()
    except Exception as exc:
        logger.warning("[server] failed to delete session %s: %s", session_id, exc)
        return {}


# ── Conversation loop ───────────────────────────────────────────────────────


async def run_conversation(
    criteria: TestCaseCriteria,
    user_proxy_config: UserProxyConfig,
    server_url: str,
    http: aiohttp.ClientSession,
    session_id: str,
    trial_label: str,
    prompt_timeout: float = 600.0,
) -> tuple[ChatHistory, list[dict]]:
    user_proxy = UserProxy(
        model=user_proxy_config.model,
        max_tokens=user_proxy_config.max_tokens,
        task_summary=criteria.task_summary,
        use_expert_agent=user_proxy_config.use_expert_agent,
        api_key=user_proxy_config.api_key,
        api_base=user_proxy_config.api_base,
    )

    chat = ChatHistory(id=str(uuid4()), conversations=[])
    turn_meta: list[dict] = []
    max_turns = criteria.max_turns

    logger.info("=" * 70)
    logger.info("%s | max_turns=%d", trial_label, max_turns)
    logger.info("task: %s", criteria.task_summary)
    logger.info("=" * 70)

    for turn_number in range(1, max_turns + 1):
        logger.info(
            "\n====== %s | turn %d/%d ======", trial_label, turn_number, max_turns
        )

        user_message = await user_proxy.generate_message(chat)
        if user_message is None:
            logger.info("User proxy returned None, ending.")
            break

        if user_message.check and not user_message.message_str:
            logger.info(
                "Terminating (empty message with check): %s", user_message.check
            )
            break

        logger.info("[user] %s", user_message.message_str)

        turn_start = time.monotonic()
        response = await send_turn(
            server_url, http, session_id, user_message.message_str, prompt_timeout
        )
        latency_ms = (time.monotonic() - turn_start) * 1000

        agent_text = response.get("answer", "")
        steps = response.get("steps", [])
        usage = response.get("usage", {})

        logger.info("[agent] %s", agent_text[:200])
        logger.info(
            "[stats] tokens=%s cost=%s latency=%.0fms",
            usage.get("total"),
            usage.get("cost"),
            latency_ms,
        )

        chat.conversations.append(
            ConversationTurn(
                id=str(uuid4()),
                user_message=user_message,
                agent_responses=[ResponseFromAgent(response_str=agent_text)],
            )
        )
        turn_meta.append({"steps": steps, "usage": usage, "latency_ms": latency_ms})

        if user_message.check is not None:
            logger.info("Terminating condition met: %s", user_message.check)
            break
    else:
        logger.info("Reached max_turns (%d).", max_turns)

    logger.info("Conversation done. %d turn(s).", len(chat.conversations))
    return chat, turn_meta


def _copy_skills_into_workspace(workspace: str, skills_dir: str) -> None:
    """Copy the contents of skills_dir into workspace/skills/."""
    target = os.path.join(workspace, "skills")
    shutil.copytree(skills_dir, target, dirs_exist_ok=True)


# ── Single trial ────────────────────────────────────────────────────────────


async def _setup_trial_workspace(
    server_config: ServerConfig,
    case_id: str,
    trial_id: int,
) -> Optional[str]:
    """Copy the environment template and skills into a temp workspace."""
    env_template = server_config.env
    if not env_template:
        return None
    env_copy = tempfile.mkdtemp(prefix=f"ws_{case_id}_t{trial_id}_")
    await asyncio.to_thread(
        shutil.copytree, env_template, env_copy, dirs_exist_ok=True
    )
    if server_config.skills_dir:
        await asyncio.to_thread(
            _copy_skills_into_workspace, env_copy, server_config.skills_dir
        )
    return env_copy


def _save_trial_artifacts(
    case_dir: str,
    run_id: str,
    chat: ChatHistory,
    turn_meta: list[dict],
    test_case_path: str,
    trajectory: Optional[dict] = None,
) -> None:
    """Write conversation.json, copy the test case YAML, and save the trace.

    ``trajectory`` is the per-harness trajectory harvested by post_run.py (if the
    harness captures it): {"turns": [{"steps": [...]}, ...]}. Its per-turn steps
    are merged into the trace by turn index, enriching the dialogue-only trace
    with the agent's tool calls, outputs and reasoning.
    """
    traj_turns = (trajectory or {}).get("turns") or []
    Path(case_dir, "conversation.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "conversations": [
                    dataclasses.asdict(c) for c in chat.conversations
                ],
                "turn_meta": turn_meta,
            },
            indent=2,
            default=str,
        )
    )
    shutil.copy2(
        test_case_path, os.path.join(case_dir, os.path.basename(test_case_path))
    )

    all_turns = []
    for i, (conv, meta) in enumerate(zip(chat.conversations, turn_meta)):
        # Prefer the harvested trajectory's steps for this turn; fall back to the
        # (usually empty) steps the turn executor returned.
        steps = meta.get("steps", [])
        if i < len(traj_turns) and traj_turns[i].get("steps"):
            steps = traj_turns[i]["steps"]
        all_turns.append(
            {
                "user_input": conv.user_message.message_str,
                "answer": (
                    conv.agent_responses[0].response_str
                    if conv.agent_responses
                    else ""
                ),
                "steps": steps,
                "usage": meta.get("usage", {}),
                "latency_ms": meta.get("latency_ms"),
            }
        )

    trace = load_trace_from_server_turns(all_turns)
    save_trace(trace, Path(case_dir, f"trace_{run_id}.json"))


async def run_single_trial(
    test_case_path: str,
    user_proxy_config: UserProxyConfig,
    server_config: ServerConfig,
    output_dir: str,
    trial_id: int,
    n_trials: int,
) -> TrialResult:
    criteria = parse_test_case(test_case_path)
    case_id = criteria.case_id
    run_id = str(uuid4())
    trial_label = f"{case_id} | trial {trial_id}/{n_trials}"

    case_dir = os.path.join(output_dir, case_id, f"trial_{trial_id}")
    os.makedirs(case_dir, exist_ok=True)
    logger.info("[%s] starting (run=%s)", trial_label, run_id)

    env_copy = await _setup_trial_workspace(server_config, case_id, trial_id)

    session_id = None
    connector = aiohttp.TCPConnector(force_close=True)
    async with aiohttp.ClientSession(connector=connector) as http:
        try:
            session_id = await create_session(
                server_config.url,
                http,
                workspace=env_copy,
                harness=server_config.harness,
            )
            logger.info("[%s] session ready: %s", trial_label, session_id)

            chat, turn_meta = await run_conversation(
                criteria,
                user_proxy_config,
                server_config.url,
                http,
                session_id,
                trial_label,
                prompt_timeout=server_config.prompt_timeout,
            )

            # Close the session first: this triggers the harness's post_run.py
            # (while the container is still alive) which harvests the full
            # trajectory. We then fold that into the saved trace.
            usage = (await delete_session(server_config.url, http, session_id)).get(
                "usage"
            ) or {}
            session_id = None
            trajectory = (usage.get("post_run") or {}).get("trajectory")

            _save_trial_artifacts(
                case_dir, run_id, chat, turn_meta, test_case_path, trajectory
            )

            usage["turn_latency_ms"] = sum(m.get("latency_ms") or 0 for m in turn_meta)
            usage["turns"] = len(chat.conversations)
            Path(case_dir, "usage.json").write_text(json.dumps(usage, indent=2))

            return TrialResult(
                trial_id=trial_id,
                sample_id=case_id,
                run_id=run_id,
                total_turns=len(chat.conversations),
                case_dir=case_dir,
                usage=usage,
            )

        except Exception as exc:
            logger.error("[%s] failed: %s", trial_label, exc, exc_info=True)
            return TrialResult(
                trial_id=trial_id,
                sample_id=case_id,
                run_id=run_id,
                status="failed",
                error=str(exc),
            )
        finally:
            if session_id:
                await delete_session(server_config.url, http, session_id)
            if env_copy:
                shutil.rmtree(env_copy, ignore_errors=True)


# ── Resume helpers ──────────────────────────────────────────────────────────


def _load_failed_trials(job_dir: str) -> List[Dict[str, Any]]:
    summary_path = os.path.join(job_dir, "runs_summary.json")
    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"No runs_summary.json in {job_dir}")
    data = json.loads(Path(summary_path).read_text())
    return [
        result for result in data.get("results", []) if result.get("status") == "failed"
    ]


def _match_case_file(sample_id: str, case_files: List[str]) -> Optional[str]:
    for case_file in case_files:
        criteria = parse_test_case(case_file)
        if criteria.case_id == sample_id:
            return case_file
    return None


async def run_resume(
    job_dir: str,
    case_files: List[str],
    user_proxy_config: UserProxyConfig,
    server_config: ServerConfig,
    n_trials: int,
    max_workers: int,
) -> List[TrialResult]:
    failed = _load_failed_trials(job_dir)
    if not failed:
        logger.info("No failed trials found.")
        return []

    logger.info("Resuming %d failed trial(s) from %s", len(failed), job_dir)
    semaphore = asyncio.Semaphore(max_workers)

    async def _run(entry: Dict[str, Any]) -> TrialResult:
        sample_id = entry["sample_id"]
        trial_id = entry["trial_id"]
        case_file = _match_case_file(sample_id, case_files)
        if case_file is None:
            return TrialResult(
                trial_id=trial_id,
                sample_id=sample_id,
                run_id="",
                status="failed",
                error=f"Test case not found for {sample_id}",
            )
        async with semaphore:
            return await run_single_trial(
                case_file,
                user_proxy_config,
                server_config,
                job_dir,
                trial_id,
                n_trials,
            )

    return list(await asyncio.gather(*[_run(entry) for entry in failed]))


def merge_runs_summary(job_dir: str, new_results: List[TrialResult]) -> None:
    summary_path = os.path.join(job_dir, "runs_summary.json")
    data = json.loads(Path(summary_path).read_text())
    old_results = data.get("results", [])
    new_keys = {(result.sample_id, result.trial_id) for result in new_results}
    merged = [
        result
        for result in old_results
        if (result["sample_id"], result["trial_id"]) not in new_keys
    ]
    merged.extend(result.to_dict() for result in new_results)

    success_count = sum(1 for result in merged if result.get("status") == "success")
    failure_count = sum(1 for result in merged if result.get("status") == "failed")
    data.update(
        total=len(merged),
        successful=success_count,
        failed=failure_count,
        results=merged,
    )
    Path(summary_path).write_text(json.dumps(data, indent=2, default=str))
    logger.info(
        "Updated runs_summary.json: %d/%d succeeded", success_count, len(merged)
    )


# ── Batch execution ─────────────────────────────────────────────────────────


async def run_all(
    case_files: List[str],
    user_proxy_config: UserProxyConfig,
    server_config: ServerConfig,
    output_dir: str,
    n_trials: int,
    max_workers: int,
) -> List[TrialResult]:
    semaphore = asyncio.Semaphore(max_workers)

    async def _run(path: str, trial: int) -> TrialResult:
        async with semaphore:
            return await run_single_trial(
                path,
                user_proxy_config,
                server_config,
                output_dir,
                trial,
                n_trials,
            )

    tasks = [
        _run(path, trial) for path in case_files for trial in range(1, n_trials + 1)
    ]
    return list(await asyncio.gather(*tasks))


async def run_selected(
    selected: List[tuple[str, int]],
    user_proxy_config: UserProxyConfig,
    server_config: ServerConfig,
    output_dir: str,
    n_trials: int,
    max_workers: int,
) -> List[TrialResult]:
    """Run only the given ``(case_file, trial_id)`` pairs into ``output_dir``."""
    semaphore = asyncio.Semaphore(max_workers)

    async def _run(path: str, trial: int) -> TrialResult:
        async with semaphore:
            return await run_single_trial(
                path,
                user_proxy_config,
                server_config,
                output_dir,
                trial,
                n_trials,
            )

    tasks = [_run(path, trial) for path, trial in selected]
    return list(await asyncio.gather(*tasks))


def fetch_server_info(server_url: str) -> dict:
    """Ask the gateway which harness/model it serves (for the runs summary)."""
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"{server_url.rstrip('/')}/healthz", timeout=10
        ) as response:
            return json.loads(response.read())
    except Exception as exc:
        # Expected to fail when e2e probes before auto-starting a server.
        logger.debug("could not fetch /healthz from %s: %s", server_url, exc)
        return {}


def save_runs_summary(
    results: List[TrialResult],
    output_dir: str,
    n_trials: int = 0,
    server_info: Optional[dict] = None,
) -> None:
    successful = [result for result in results if result.status == "success"]
    failed_results = [result for result in results if result.status == "failed"]
    n_samples = len(set(result.sample_id for result in results))
    expected = n_samples * n_trials if n_trials else len(results)
    data = {
        "harness": (server_info or {}).get("harness", ""),
        "model": (server_info or {}).get("model", ""),
        "n_samples": n_samples,
        "n_trials": n_trials,
        "expected_runs": expected,
        "successful": len(successful),
        "failed": len(failed_results),
        "results": [result.to_dict() for result in results],
    }
    summary_path = os.path.join(output_dir, "runs_summary.json")
    Path(summary_path).write_text(json.dumps(data, indent=2, default=str))
    logger.info("Saved runs summary -> %s", summary_path)
