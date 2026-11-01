#!/usr/bin/env python3
"""Docker container lifecycle for harness evaluation.

_DockerContainer handles raw Docker operations (start/stop/port/logs).
HarnessInstance wraps it with harness-aware orchestration (pre_run, turn
dispatch, post_run).

Lifecycle: construct -> open() -> ask(utterance) N times -> close().
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from typing import Any, Optional

from server import HarnessError, DOCKER

DEFAULT_PROMPT_TIMEOUT = 600.0

DEFAULT_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "container_logs"
)


class _DockerContainer:
    """Manages one Docker container's lifecycle (start, stop, port resolution).

    Usage as a context manager guarantees the container is torn down::

        with _DockerContainer("harness-pi", keepalive=True) as c:
            subprocess.run(["docker", "exec", c.name, "echo", "hi"])
    """

    def __init__(
        self,
        image: str,
        *,
        model: Optional[str] = None,
        workspace: Optional[str] = None,
        env_keys: tuple[str, ...] = (),
        name: Optional[str] = None,
        log_dir: Optional[str] = DEFAULT_LOG_DIR,
        keepalive: bool = False,
        serve_port: Optional[int] = None,
        mount_target: str = "/workspace",
        static_env: Optional[dict] = None,
    ) -> None:
        if not image:
            raise HarnessError("a Docker image name is required")
        self.image = image
        self.model = model
        self.workspace = workspace
        self.env_keys = env_keys
        self.mount_target = mount_target
        self._serve_port = serve_port
        self._static_env = static_env or {}
        self.host_port: Optional[int] = None
        self.name = name or f"harness-{uuid.uuid4().hex[:12]}"
        self._keepalive = keepalive

        self.log_dir: Optional[str] = (
            os.path.join(log_dir, self.name) if log_dir else None
        )
        self._stderr_path: Optional[str] = (
            os.path.join(self.log_dir, "stderr.log") if self.log_dir else None
        )
        self._stderr_file = None

        self._process: Optional[subprocess.Popen] = None
        self._stdout_reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._closed = False

    def _build_command(self) -> list[str]:
        command = [
            DOCKER,
            "run",
            "--rm",
            "--name",
            self.name,
            "--add-host=host.docker.internal:host-gateway",
        ]
        for key in self.env_keys:
            if key in os.environ:
                command += ["-e", f"{key}={os.environ[key]}"]
        if self.workspace:
            command += ["-v", f"{os.path.abspath(self.workspace)}:{self.mount_target}"]
        if self._serve_port:
            for env_name, env_value in self._static_env.items():
                command += ["-e", f"{env_name}={env_value}"]
            command += ["-p", f"127.0.0.1::{self._serve_port}"]
            return command + [self.image]
        if self._keepalive:
            return command + ["--entrypoint", "tail", self.image, "-f", "/dev/null"]
        raise HarnessError(
            "_DockerContainer requires either serve_port or keepalive=True"
        )

    def resolve_host_port(self, retries: int = 30) -> int:
        for _ in range(retries):
            result = subprocess.run(
                [DOCKER, "port", self.name, f"{self._serve_port}/tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and ":" in result.stdout:
                self.host_port = int(
                    result.stdout.strip().splitlines()[0].rsplit(":", 1)[1]
                )
                return self.host_port
            time.sleep(0.5)
        raise HarnessError(
            f"docker never reported a host port for "
            f"{self._serve_port}/tcp on {self.name}"
        )

    def start(self) -> "_DockerContainer":
        if self._process is not None:
            raise HarnessError("container already started")
        self._process = subprocess.Popen(
            self._build_command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stdout_reader = threading.Thread(target=self._drain_stdout, daemon=True)
        self._stdout_reader.start()
        if self._stderr_path:
            try:
                os.makedirs(self.log_dir, exist_ok=True)
                self._stderr_file = open(
                    self._stderr_path, "a", encoding="utf-8", buffering=1
                )
            except OSError:
                self._stderr_file = None
        self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_reader.start()
        return self

    def _drain_stdout(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        for _ in self._process.stdout:
            pass

    def _drain_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        for line in self._process.stderr:
            file_handle = self._stderr_file
            if file_handle is None:
                continue
            try:
                file_handle.write(line if line.endswith("\n") else line + "\n")
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except Exception:
                self._process.kill()
        subprocess.run(
            [DOCKER, "rm", "-f", self.name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if self._stderr_file is not None:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

    def __enter__(self) -> "_DockerContainer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()


# ── Harness-level orchestration ──────────────────────────────────────────────


def _load_strip_noise(harness_dir):
    path = os.path.join(harness_dir, "strip_noise.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("strip_noise", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "strip", None)


def _skill_content_lines(workspace):
    if not workspace:
        return frozenset()
    import glob as _glob

    lines = set()
    for pattern in ("skills/*/SKILL.md", ".pi/skills/*/SKILL.md"):
        for path in _glob.glob(os.path.join(workspace, pattern)):
            try:
                text = open(path).read()
            except OSError:
                continue
            lines.update(
                stripped
                for stripped in (line.strip() for line in text.splitlines())
                if stripped
            )
            try:
                import yaml as _yaml

                parts = text.split("---", 2)
                if len(parts) >= 3:
                    description = (_yaml.safe_load(parts[1]) or {}).get(
                        "description", ""
                    )
                    lines.update(
                        stripped
                        for stripped in (
                            line.strip() for line in description.splitlines()
                        )
                        if stripped
                    )
            except Exception:
                pass
    return frozenset(lines)


class HarnessInstance:
    """A long-lived, managed harness container.

    Drives harnesses via CLI (docker exec) or HTTP (long-lived server).
    Set by `turn_mode: cli` or `turn_mode: http` in harness.yaml.
    """

    def __init__(
        self,
        image: str,
        harness_config: Optional[dict] = None,
        proxy_base: Optional[str] = None,
        api_key: str = "dummy",
        **container_kwargs: Any,
    ) -> None:
        self._harness_config = harness_config or {
            "cmd": ["pi", "--print", "--no-extensions"],
            "model_flag": "--model",
            "session_flag": "-c",
            "workdir": "/workspace",
        }
        container_kwargs.setdefault(
            "env_keys", tuple(self._harness_config.get("env_keys") or ())
        )
        uses_http = self._harness_config.get("turn_mode") == "http"
        http_server = self._harness_config.get("http_server") or {}
        if uses_http:
            container_kwargs.setdefault("serve_port", int(http_server.get("port", 3000)))
            container_kwargs.setdefault(
                "mount_target",
                self._harness_config.get("workspace_mount", "/workspace"),
            )
            container_kwargs.setdefault(
                "static_env",
                {
                    key: value
                    for key, value in (self._harness_config.get("env") or {}).items()
                    if "{" not in str(value)
                },
            )
        self._container = _DockerContainer(
            image, keepalive=not uses_http, **container_kwargs
        )
        self._proxy_base = proxy_base or ""
        self._api_key = api_key
        self._harness_dir = self._harness_config.get("_harness_dir")
        self._strip_fn = None
        if self._harness_dir:
            self._strip_fn = _load_strip_noise(self._harness_dir)
        self._skill_lines: Optional[frozenset] = None
        self._turn_lock = threading.Lock()
        self._turn_count = 0
        self._session_id: Optional[str] = None
        self._opened = False

    @property
    def name(self) -> str:
        return self._container.name

    def open(self) -> "HarnessInstance":
        if self._opened:
            return self
        self._container.start()
        model = self._container.model or ""
        self._wait_for_container_start()
        self._wait_for_workspace_mount()
        self._run_pre_run_script(model)
        self._wait_for_health()
        self._opened = True
        return self

    def _wait_for_container_start(self) -> None:
        name = self._container.name
        for _ in range(20):
            inspect_result = subprocess.run(
                [DOCKER, "inspect", "--format", "{{.State.Status}}", name],
                capture_output=True,
                text=True,
                check=False,
            )
            if inspect_result.stdout.strip() == "running":
                return
            time.sleep(0.25)

    def _wait_for_workspace_mount(self) -> None:
        workspace_dir = self._container.workspace
        mount_target = self._container.mount_target
        if not (workspace_dir and os.path.isdir(workspace_dir) and os.listdir(workspace_dir)):
            return
        name = self._container.name
        for _ in range(60):
            mount_check = subprocess.run(
                [
                    DOCKER,
                    "exec",
                    name,
                    "sh",
                    "-c",
                    f"ls -A {mount_target} | head -1",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if mount_check.stdout.strip():
                return
            time.sleep(0.5)
        raise HarnessError(
            f"mounted {mount_target} still empty after 30s in {name}"
        )

    def _run_pre_run_script(self, model: str) -> None:
        if not self._harness_dir:
            return
        server_dir = os.path.dirname(os.path.abspath(__file__))
        setup_script = os.path.join(server_dir, "container_setup.py")
        pre_run_script = os.path.join(self._harness_dir, "pre_run.py")
        if not os.path.isfile(pre_run_script):
            return
        name = self._container.name
        subprocess.run(
            [DOCKER, "cp", setup_script, f"{name}:/tmp/container_setup.py"],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            [DOCKER, "cp", pre_run_script, f"{name}:/tmp/pre_run.py"],
            capture_output=True,
            check=False,
        )
        skills_csv = ",".join(self._harness_config.get("skills_dirs") or [])
        exec_result = subprocess.run(
            [
                DOCKER,
                "exec",
                "-e",
                f"HARNESS_PROXY_BASE={self._proxy_base or ''}",
                "-e",
                f"HARNESS_MODEL={model}",
                "-e",
                f"HARNESS_API_KEY={self._api_key}",
                "-e",
                f"HARNESS_SKILLS_DIRS={skills_csv}",
                name,
                "python3",
                "/tmp/pre_run.py",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if exec_result.stderr:
            logging.getLogger(__name__).info(
                "pre_run stderr: %s", exec_result.stderr[-1000:]
            )
        if exec_result.returncode != 0:
            raise HarnessError(
                f"pre_run.py failed: rc={exec_result.returncode} "
                f"stdout={exec_result.stdout[-500:]!r} "
                f"stderr={exec_result.stderr[-500:]!r}"
            )
        # tidy up one-shot setup files
        subprocess.run(
            [DOCKER, "exec", name, "rm", "-f",
             "/tmp/pre_run.py", "/tmp/container_setup.py"],
            capture_output=True,
            check=False,
        )

    def _wait_for_health(self) -> None:
        if self._harness_config.get("turn_mode") != "http":
            return
        http_server_config = self._harness_config.get("http_server") or {}
        if not http_server_config:
            return
        import urllib.request

        self._container.resolve_host_port()
        health_url = (
            f"http://localhost:{self._container.host_port}"
            f"{http_server_config.get('health', '/')}"
        )
        name = self._container.name
        for _ in range(60):
            try:
                urllib.request.urlopen(health_url, timeout=2)
                return
            except OSError:
                time.sleep(1)
        raise HarnessError(
            f"server in {name} never became healthy at {health_url}"
        )

    def ask(self, utterance: str, timeout: float = DEFAULT_PROMPT_TIMEOUT) -> str:
        return self.ask_detailed(utterance, timeout=timeout)["answer"]

    def ask_detailed(
        self, utterance: str, timeout: float = DEFAULT_PROMPT_TIMEOUT
    ) -> dict:
        if not self._opened:
            raise HarnessError("instance not open(); call open() first")
        with self._turn_lock:
            self._turn_count += 1
            if self._harness_config.get("turn_mode") == "http":
                from turn.turn_http import run_turn

                result = run_turn(
                    self._container.host_port,
                    self._harness_config,
                    utterance,
                    self._turn_count,
                    self._session_id,
                    timeout,
                )
            else:
                from turn.turn_cli import run_turn

                if self._skill_lines is None:
                    self._skill_lines = _skill_content_lines(self._container.workspace)
                result = run_turn(
                    self._container.name,
                    self._harness_config,
                    utterance,
                    self._turn_count,
                    self._session_id,
                    self._container.model or "",
                    self._proxy_base,
                    self._api_key,
                    self._strip_fn,
                    self._skill_lines,
                    timeout,
                )
            self._session_id = result.pop("session_id", self._session_id)
        return result

    def stats(self) -> dict:
        return {"turns": self._turn_count}

    def abort(self) -> None:
        pass

    def close(self) -> dict:
        post_run_result = {}
        if self._harness_dir and self._opened:
            post_run_script = os.path.join(self._harness_dir, "post_run.py")
            if os.path.isfile(post_run_script):
                post_run_proc = subprocess.run(
                    ["python3", post_run_script, self._container.name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if post_run_proc.returncode == 0 and post_run_proc.stdout.strip():
                    try:
                        post_run_result = json.loads(post_run_proc.stdout.strip())
                    except json.JSONDecodeError:
                        logging.getLogger(__name__).warning(
                            "post_run.py stdout not valid JSON: %s",
                            post_run_proc.stdout[:200],
                        )
                if post_run_proc.stderr:
                    logging.getLogger(__name__).info(
                        "post_run stderr: %s", post_run_proc.stderr[-500:]
                    )
        self._post_run_result = post_run_result
        self._container.close()
        self._opened = False
        return post_run_result

    def __enter__(self) -> "HarnessInstance":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()
