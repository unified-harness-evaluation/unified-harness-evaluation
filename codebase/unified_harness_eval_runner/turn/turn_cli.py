#!/usr/bin/env python3
"""Execute one CLI-mode turn via docker exec."""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Optional

from server import DOCKER


def run_turn(
    container_name: str,
    config: dict,
    utterance: str,
    turn_count: int,
    session_id: Optional[str],
    model: str,
    proxy_base: str,
    api_key: str,
    strip_fn,
    skill_lines: frozenset,
    timeout: float,
) -> dict:
    """Run one CLI turn via docker exec."""

    def _expand(template: str) -> str:
        return template.format(
            task=utterance,
            model=model,
            proxy_base=proxy_base,
            api_key=api_key,
            session_id=session_id or "",
        )

    command = [DOCKER, "exec"]
    for env_name, value_template in config.get("env", {}).items():
        command += ["-e", f"{env_name}={_expand(value_template)}"]
    command += ["-w", config.get("workdir", "/workspace"), container_name]

    session_config = config.get("session", {})

    harness_cmd = config.get("cmd", ["pi", "--print", "--no-extensions"])
    resume_cmd = (session_config.get("resume_cmd") if session_config else None) or []
    using_resume_cmd = turn_count > 1 and bool(resume_cmd)
    if using_resume_cmd:
        harness_cmd = resume_cmd
    if any("{task}" in part for part in harness_cmd):
        expanded = [_expand(part) for part in harness_cmd]
    else:
        expanded = list(harness_cmd)
        if model and config.get("model_flag"):
            expanded += [config["model_flag"], model]
        expanded.append(utterance)

    turn1_flag = session_config.get("turn1_flag") if session_config else None
    if turn_count == 1 and turn1_flag:
        if isinstance(turn1_flag, list):
            expanded.extend(_expand(flag_item) for flag_item in turn1_flag)
        else:
            expanded.append(_expand(str(turn1_flag)))

    session_flag = (
        session_config.get("flag") if session_config else config.get("session_flag")
    )
    if not session_flag:
        session_flag = config.get("session_flag")
    always = bool(session_config.get("always"))

    skip_flag_turn1 = turn_count == 1 and bool(turn1_flag)
    flag_needs_session_id = session_flag and any(
        "{session_id}" in str(flag_part)
        for flag_part in (
            session_flag if isinstance(session_flag, list) else [session_flag]
        )
    )
    if (
        not skip_flag_turn1
        and not using_resume_cmd
        and (always or (turn_count > 1 and session_flag))
    ):
        if not (flag_needs_session_id and not session_id):
            flag_list = (
                [_expand(flag_part) for flag_part in session_flag]
                if isinstance(session_flag, list)
                else [_expand(str(session_flag))]
                if session_flag
                else []
            )
            task_index = next(
                (index for index, part in enumerate(harness_cmd) if "{task}" in part),
                None,
            )
            if session_config.get("flag_before_task") and task_index is not None:
                expanded[task_index:task_index] = flag_list
            else:
                expanded.extend(flag_list)

    command += expanded
    start_time = time.monotonic()
    result = None
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if not output and stderr:
            output = stderr[-2000:]
        elif result.returncode != 0 and stderr:
            output += f"\n[stderr: {stderr[-500:]}]\n[exit code {result.returncode}]"
    except subprocess.TimeoutExpired:
        output = f"ERROR: timed out after {timeout}s"
    latency_ms = (time.monotonic() - start_time) * 1000.0

    output = "\n".join(
        line
        for line in output.splitlines()
        if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[", line)
    ).strip()

    new_session_id = session_id
    session_id_regex = (
        session_config.get("session_id_regex") if session_config else None
    )
    session_id_command = (
        session_config.get("session_id_cmd") if session_config else None
    )
    if new_session_id is None and (session_id_regex or session_id_command):
        if session_id_command:
            session_id_process = subprocess.run(
                [DOCKER, "exec", container_name]
                + (
                    session_id_command
                    if isinstance(session_id_command, list)
                    else ["sh", "-c", session_id_command]
                ),
                capture_output=True,
                text=True,
                timeout=10,
            )
            session_id_source = session_id_process.stdout.strip()
        else:
            session_id_source = (result.stdout if result is not None else "") or ""
        if session_id_source:
            if session_id_regex:
                match = re.search(session_id_regex, session_id_source)
                if match:
                    new_session_id = match.group(1)
            else:
                new_session_id = session_id_source.splitlines()[0].strip()

    if config.get("json_extract_final"):
        output = _extract_json_final(output)

    if strip_fn:
        output = strip_fn(output, skill_lines=skill_lines)
    else:
        output = _default_strip(output)
    if not output:
        output = "Done."

    return {
        "answer": output,
        "session_id": new_session_id,
        "steps": [],
        "usage": {},
        "skill_calls": [],
        "latency_in_ms": latency_ms,
    }


def _extract_json_final(output: str) -> str:
    texts: list[str] = []
    tokens: list[str] = []
    errors: list[str] = []
    all_json = True
    for line in output.split("\n"):
        try:
            event = json.loads(line)
            if (
                event.get("type") in ("final", "run_result")
                and event.get("text", "").strip()
            ):
                return event["text"]
            if event.get("type") == "content" and isinstance(event.get("content"), str):
                tokens.append(event["content"])
            if event.get("type") == "text":
                text_content = (event.get("part") or {}).get("text") or event.get(
                    "text"
                )
                if text_content and isinstance(text_content, str):
                    texts.append(text_content)
            if event.get("type") == "error":
                error_value = event.get("error")
                if isinstance(error_value, dict):
                    data = error_value.get("data")
                    message = (
                        (
                            (data or {}).get("message")
                            if isinstance(data, dict)
                            else None
                        )
                        or error_value.get("message")
                        or event.get("message")
                        or str(event)
                    )
                else:
                    message = error_value or event.get("message") or str(event)
                errors.append(message)
            if (
                event.get("type") == "status"
                and event.get("phase") == "turn_end"
                and (event.get("reason") or {}).get("kind") == "error"
            ):
                errors.append(
                    event["reason"].get("error", {}).get("message", str(event))
                )
        except (ValueError, KeyError):
            all_json = False
    if texts:
        return "\n".join(texts)
    if tokens:
        return "".join(tokens)
    if errors:
        return "\n".join(errors)
    if all_json:
        return ""
    return output


def _default_strip(output: str) -> str:
    output = re.sub(r"\x1b\[[0-9;]*m", "", output)
    output = re.sub(r"<\|[^|]+\|>", "", output)
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines).strip()
