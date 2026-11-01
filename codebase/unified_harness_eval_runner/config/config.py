"""Centralised constants and typed configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

import yaml

from config.testcase import iter_case_files

# ── Paths ────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUTPUT_ROOT = str(_REPO_ROOT / "experiment_results")
DEFAULT_RUNNER_CONFIG = str(_REPO_ROOT / "runner_config.yaml")


# ── Sub-config dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class UserProxyConfig:
    model: str = "azure/gpt-5.4"
    max_tokens: int = 4096
    use_expert_agent: bool = True
    api_key: Optional[str] = None
    api_base: Optional[str] = None


@dataclass(frozen=True)
class JudgeConfig:
    model: str = "azure/gpt-5.4"
    max_tokens: int = 4096
    num_judge_trials: int = 1
    api_key: Optional[str] = None
    api_base: Optional[str] = None


@dataclass(frozen=True)
class ServerConfig:
    url: str = "http://localhost:9000"
    prompt_timeout: float = 600.0
    harness: Optional[str] = None
    env: Optional[str] = None
    skills_dir: Optional[str] = None
    litellm_port: int = 4001
    log_dir: str = "container_logs"
    max_workspace_wait: int = 30


# ── Unified experiment config ───────────────────────────────────────────────


@dataclass(frozen=True)
class Experiment:
    config_path: str = DEFAULT_RUNNER_CONFIG
    harnesses: List[str] = field(default_factory=lambda: ["pi"])
    case_files: List[str] = field(default_factory=list)
    model: str = "claude-opus-4-6"
    trial_count: int = 1
    concurrency: int = 5
    base_port: int = 9000
    timeout_per_turn: float = 600.0
    health_timeout: int = 60
    strict: bool = False
    env: Optional[str] = None
    results_dir: str = DEFAULT_OUTPUT_ROOT

    user_proxy: UserProxyConfig = field(default_factory=UserProxyConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


# ── Config loading ──────────────────────────────────────────────────────────


def _load_runner_config(path: Optional[str] = None) -> dict:
    config_path = path or DEFAULT_RUNNER_CONFIG
    if not os.path.exists(config_path):
        if os.path.abspath(config_path) == os.path.abspath(DEFAULT_RUNNER_CONFIG):
            raise FileNotFoundError(
                f"{config_path} not found. Create it from the annotated template: "
                f"cp runner_config.yaml.example runner_config.yaml"
            )
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path) as file_handle:
        return yaml.safe_load(file_handle) or {}


def _resolve_llm_creds(section: dict) -> tuple[Optional[str], Optional[str]]:
    api_key = section.get("api_key") or os.environ.get("AZURE_API_KEY")
    api_base = section.get("api_base") or os.environ.get("AZURE_API_BASE")
    return api_key, api_base


def _user_proxy_config_from(raw_config: dict) -> UserProxyConfig:
    section = raw_config.get("user_proxy") or {}
    api_key, api_base = _resolve_llm_creds(section)
    return UserProxyConfig(
        model=section.get("model", UserProxyConfig.model),
        max_tokens=section.get("max_tokens", UserProxyConfig.max_tokens),
        use_expert_agent=section.get(
            "use_expert_agent", UserProxyConfig.use_expert_agent
        ),
        api_key=api_key,
        api_base=api_base,
    )


def _judge_config_from(raw_config: dict) -> JudgeConfig:
    section = raw_config.get("judge") or {}
    api_key, api_base = _resolve_llm_creds(section)
    return JudgeConfig(
        model=section.get("model", JudgeConfig.model),
        max_tokens=section.get("max_tokens", JudgeConfig.max_tokens),
        num_judge_trials=section.get("num_judge_trials", JudgeConfig.num_judge_trials),
        api_key=api_key,
        api_base=api_base,
    )


def _server_config_from(raw_config: dict) -> ServerConfig:
    server_section = raw_config.get("server") or {}
    run_section = raw_config.get("run") or {}
    skills_dir_value = raw_config.get("skills_dir") or raw_config.get("skills")
    if isinstance(skills_dir_value, dict):
        skills_dir_value = skills_dir_value.get("path")
    skills_dir = _resolve_repo_path(skills_dir_value) if skills_dir_value else None
    port = run_section.get("base_port", server_section.get("port", 9000))
    return ServerConfig(
        url=server_section.get("url", f"http://localhost:{port}"),
        prompt_timeout=run_section.get(
            "timeout_per_turn",
            server_section.get("prompt_timeout", ServerConfig.prompt_timeout),
        ),
        env=run_section.get("env") or run_section.get("workspace"),
        skills_dir=skills_dir,
        litellm_port=server_section.get("litellm_port", ServerConfig.litellm_port),
        log_dir=server_section.get("log_dir", ServerConfig.log_dir),
        max_workspace_wait=server_section.get(
            "max_workspace_wait", ServerConfig.max_workspace_wait
        ),
    )


def _resolve_repo_path(relative_path: str) -> str:
    path = Path(relative_path)
    return str(path if path.is_absolute() else _REPO_ROOT / path)


def load_experiment(config_path: Optional[str] = None) -> Experiment:
    config_path = config_path or DEFAULT_RUNNER_CONFIG
    raw_config = _load_runner_config(config_path)

    run_section = raw_config.get("run") or raw_config.get("experiment") or {}
    agent_section = raw_config.get("agent") or raw_config.get("agent_harness") or {}

    harnesses = run_section.get("harnesses") or ["pi"]
    if isinstance(harnesses, str):
        harnesses = [harnesses]

    results_dir = run_section.get("results_dir")

    tests_value = run_section.get("tests")
    if tests_value is None:
        tests_value = str(_REPO_ROOT / "test_cases")
    if isinstance(tests_value, str):
        tests_value = [tests_value]
    case_files = []
    for path in tests_value:
        resolved = _resolve_repo_path(path)
        case_files.extend(iter_case_files(resolved))

    return Experiment(
        config_path=config_path,
        harnesses=list(harnesses),
        case_files=case_files,
        model=agent_section.get("model", Experiment.model),
        trial_count=run_section.get(
            "n_trials", run_section.get("trial_count", Experiment.trial_count)
        ),
        concurrency=run_section.get("concurrency", Experiment.concurrency),
        base_port=run_section.get("base_port", Experiment.base_port),
        timeout_per_turn=run_section.get(
            "timeout_per_turn", Experiment.timeout_per_turn
        ),
        health_timeout=run_section.get("health_timeout", Experiment.health_timeout),
        strict=run_section.get("strict", Experiment.strict),
        env=run_section.get("env") or run_section.get("workspace"),
        results_dir=_resolve_repo_path(results_dir)
        if results_dir
        else DEFAULT_OUTPUT_ROOT,
        user_proxy=_user_proxy_config_from(raw_config),
        judge=_judge_config_from(raw_config),
        server=_server_config_from(raw_config),
    )


def silence_litellm() -> None:
    import litellm

    os.environ.setdefault("LITELLM_LOG", "ERROR")
    litellm.suppress_debug_info = True
    litellm.callbacks = []
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM Router").setLevel(logging.ERROR)
