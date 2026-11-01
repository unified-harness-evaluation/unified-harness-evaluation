"""End-to-end runner: conversation phase then eval phase.

Reads everything from runner_config.yaml (or the file given by --config).
Every harness listed in run.harnesses gets a session on a single shared
gateway, runs a multi-turn conversation, then a traceless judge scores
the transcript. Results land in results_dir/<harness>/jobs/<timestamp>/.

Usage:
    python -m e2e                          # default runner_config.yaml
    python -m e2e --config other.yaml      # alternate config
    python -m e2e --resume <results_dir>/<harness>/jobs/<ts>  # retry failed
    python -m e2e --auto-check-run-missing # fill gaps in latest job, then eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import (
    DEFAULT_RUNNER_CONFIG,
    Experiment,
    ServerConfig,
    load_experiment,
)
from run.auto_check import run_one_harness_auto_check
from run.conversation import (
    fetch_server_info,
    run_all,
    save_runs_summary,
    run_resume,
    merge_runs_summary,
)
from run.evaluate_traceless import (
    discover_trial_folders,
    run_eval_batch,
    save_results,
)

logger = logging.getLogger("experiment_runner.e2e")


def _load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Zero-dependency (python-dotenv is not a project dep). Lines may use a
    leading ``export`` and single/double-quoted values. Existing environment
    variables are never overwritten, so a manual ``source .env`` still wins.
    """
    env_path = path or (Path(__file__).resolve().parent / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value



def _ensure_server(
    model: str, port: int, config_path: str, log_path: str
) -> tuple[str, Optional[subprocess.Popen]]:
    """Return (url, process) for the multi-tenant gateway.

    Reuses a gateway already running on *port*; otherwise starts one and
    waits for it to come up. Sessions name their harness per request.
    """
    url = f"http://localhost:{port}"
    info = fetch_server_info(url)
    if info.get("ok") and info.get("mode") == "multi-tenant":
        logger.info("reusing running gateway at %s", url)
        return url, None

    command = [
        sys.executable,
        "-m", "server.harness_server",
        "--model",
        model,
        "--port",
        str(port),
        "--config",
        config_path,
    ]
    log = open(log_path, "w")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(f"harness_server exited at startup; see {log_path}")
        if fetch_server_info(url).get("ok"):
            logger.info("gateway up on %s", url)
            return url, process
        time.sleep(1)
    process.terminate()
    raise RuntimeError(f"harness_server did not come up on {url}; see {log_path}")


def _stop_gateway(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _run_eval_phase(
    output_dir: str,
    judge,
    trial_count: int,
    concurrency: int,
) -> None:
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trial_folders = discover_trial_folders(Path(output_dir))
    if not trial_folders:
        return
    eval_results = asyncio.run(
        run_eval_batch(
            trial_folders,
            judge,
            trial_count,
            max_workers=concurrency,
            run_ts=run_timestamp,
        )
    )
    save_results(eval_results, trial_count, Path(output_dir), run_timestamp)


def _run_one_harness(
    harness: str,
    experiment: Experiment,
    server_config: ServerConfig,
    output_root: str,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
    output_dir = os.path.join(output_root, "jobs", timestamp)
    os.makedirs(output_dir, exist_ok=True)

    logger.info(
        "E2E [%s]: %d case(s) x %d trial(s) | workers=%d",
        harness,
        len(experiment.case_files),
        experiment.trial_count,
        experiment.concurrency,
    )

    conversation_results = asyncio.run(
        run_all(
            experiment.case_files,
            experiment.user_proxy,
            server_config,
            output_dir,
            experiment.trial_count,
            experiment.concurrency,
        )
    )
    server_info = {
        "harness": harness,
        "model": experiment.model,
        **fetch_server_info(server_config.url),
    }
    save_runs_summary(
        conversation_results, output_dir, experiment.trial_count,
        server_info=server_info,
    )

    success_count = sum(
        1 for result in conversation_results if result.status == "success"
    )
    logger.info(
        "[%s] conversation phase: %d/%d succeeded",
        harness,
        success_count,
        len(conversation_results),
    )
    for result in conversation_results:
        if result.status == "failed":
            logger.info(
                "  FAIL %s (trial %d): %s",
                result.sample_id,
                result.trial_id,
                result.error,
            )
    if success_count == 0:
        logger.info("[%s] all conversations failed; skipping eval.", harness)
        return

    _run_eval_phase(output_dir, experiment.judge, experiment.trial_count, experiment.concurrency)
    logger.info("[%s] done. Results in %s", harness, output_dir)


def _resume_job(job_dir: str, experiment: Experiment) -> None:
    """Resume a failed run: retry failed trials, then re-judge everything."""
    logger.info("RESUME mode: %s", job_dir)

    summary = json.loads(Path(job_dir, "runs_summary.json").read_text())
    harness = summary.get("harness")
    if not harness:
        raise ValueError(
            f"runs_summary.json in {job_dir} has no 'harness'; "
            "cannot determine which gateway to start"
        )
    model = summary.get("model") or experiment.model
    trial_count = summary.get("n_trials") or experiment.trial_count
    url, process = _ensure_server(
        model,
        experiment.base_port,
        experiment.config_path,
        os.path.join(job_dir, "gateway.resume.log"),
    )
    try:
        conversation_results = asyncio.run(
            run_resume(
                job_dir,
                experiment.case_files,
                experiment.user_proxy,
                replace(experiment.server, url=url, harness=harness),
                trial_count,
                experiment.concurrency,
            )
        )
    finally:
        _stop_gateway(process)
    if not conversation_results:
        logger.info("Nothing retried; skipping eval. Results in %s", job_dir)
        return
    merge_runs_summary(job_dir, conversation_results)
    success_count = sum(
        1 for result in conversation_results if result.status == "success"
    )
    logger.info(
        "Resume: %d/%d retried succeeded", success_count, len(conversation_results)
    )

    _run_eval_phase(job_dir, experiment.judge, trial_count, experiment.concurrency)
    logger.info("E2E complete. Results in %s", job_dir)


def _run_all_harnesses(experiment: Experiment, auto_check: bool = False) -> None:
    """Start the gateway, run every harness in sequence, then tear down.

    When ``auto_check`` is set, each harness reuses its latest job dir and only
    runs the trials still missing from it before evaluating.
    """
    url, process = _ensure_server(
        experiment.model, experiment.base_port, experiment.config_path,
        os.path.join(experiment.results_dir, "gateway.server.log"),
    )
    try:
        for harness in experiment.harnesses:
            root = (
                os.path.join(experiment.results_dir, harness)
                if len(experiment.harnesses) > 1
                else experiment.results_dir
            )
            os.makedirs(root, exist_ok=True)
            if os.path.exists(experiment.config_path):
                shutil.copy2(
                    experiment.config_path,
                    os.path.join(root, "runner_config.yaml"),
                )
            if auto_check:
                run_one_harness_auto_check(
                    harness, experiment,
                    replace(experiment.server, url=url, harness=harness),
                    root, _run_eval_phase,
                )
            else:
                _run_one_harness(
                    harness, experiment,
                    replace(experiment.server, url=url, harness=harness),
                    root,
                )
    finally:
        _stop_gateway(process)
    logger.info("E2E complete. Results in %s", experiment.results_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="E2E: conversation + eval, driven by runner_config.yaml"
    )
    parser.add_argument("--config", default=DEFAULT_RUNNER_CONFIG)
    parser.add_argument(
        "--resume",
        default=None,
        help="Path to a previous results/<harness>/jobs/<timestamp> directory; "
        "retries failed trials and re-runs eval",
    )
    parser.add_argument(
        "--auto-check-run-missing",
        action="store_true",
        help="Reuse each harness's latest job dir, run only the (case, trial) "
        "combinations still missing, re-check completeness, then run eval",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _load_dotenv()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    experiment = load_experiment(args.config)

    if args.resume:
        _resume_job(args.resume, experiment)
        return

    os.makedirs(experiment.results_dir, exist_ok=True)
    _run_all_harnesses(experiment, auto_check=args.auto_check_run_missing)


if __name__ == "__main__":
    main()
