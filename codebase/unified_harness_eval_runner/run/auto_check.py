"""Auto-check helper: fill in trials missing from a harness's latest job dir.

Used by e2e when ``--auto-check-run-missing`` is set. Reuses the most recent
job directory for each harness (creating one if none exists), runs only the
``(case, trial)`` combinations that have no ``conversation.json`` yet, re-checks
completeness, then hands the folder to the provided eval callback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from config import Experiment, ServerConfig, parse_test_case
from run.conversation import (
    TrialResult,
    fetch_server_info,
    run_selected,
    save_runs_summary,
)

logger = logging.getLogger("experiment_runner.auto_check")

# (output_dir, judge, trial_count, concurrency) -> None
EvalPhase = Callable[[str, object, int, int], None]


def _find_latest_job_dir(output_root: str) -> Optional[str]:
    """Return the most recent ``<output_root>/jobs/<timestamp>`` dir, or None."""
    jobs_root = Path(output_root, "jobs")
    if not jobs_root.is_dir():
        return None
    job_dirs = sorted(p for p in jobs_root.iterdir() if p.is_dir())
    return str(job_dirs[-1]) if job_dirs else None


def _case_id_map(case_files: list[str]) -> list[tuple[str, str]]:
    """Map each test case file to its case_id: [(case_file, case_id), ...]."""
    return [(case_file, parse_test_case(case_file).case_id) for case_file in case_files]


def _scan_done_trials(
    job_dir: str, case_map: list[tuple[str, str]], n_trials: int
) -> set[tuple[str, int]]:
    """(case_id, trial_id) pairs that already have a conversation.json in job_dir."""
    done: set[tuple[str, int]] = set()
    for _, case_id in case_map:
        for trial_id in range(1, n_trials + 1):
            conv = Path(job_dir, case_id, f"trial_{trial_id}", "conversation.json")
            if conv.exists():
                done.add((case_id, trial_id))
    return done


def _reconstruct_done_results(
    job_dir: str, done: set[tuple[str, int]]
) -> list[TrialResult]:
    """Rebuild TrialResult records for already-completed trials from disk."""
    results: list[TrialResult] = []
    for case_id, trial_id in sorted(done):
        conv_path = Path(job_dir, case_id, f"trial_{trial_id}", "conversation.json")
        run_id, total_turns = "", 0
        try:
            data = json.loads(conv_path.read_text())
            run_id = data.get("run_id", "") or ""
            total_turns = len(data.get("conversations") or [])
        except Exception as exc:  # pragma: no cover - defensive, corrupt file
            logger.warning("could not read %s: %s", conv_path, exc)
        results.append(
            TrialResult(
                trial_id=trial_id,
                sample_id=case_id,
                run_id=run_id,
                status="success",
                total_turns=total_turns,
                case_dir=str(conv_path.parent),
            )
        )
    return results


def run_one_harness_auto_check(
    harness: str,
    experiment: Experiment,
    server_config: ServerConfig,
    output_root: str,
    eval_phase: EvalPhase,
) -> None:
    """Fill in only the trials missing from an existing job dir, then eval.

    Reuses the most recent ``<output_root>/jobs/<ts>`` folder (creating one if
    none exists), runs only the (case, trial) combinations that have no
    conversation.json yet, re-checks completeness, then runs eval on the folder.
    """
    case_map = _case_id_map(experiment.case_files)
    n_trials = experiment.trial_count
    expected = {(case_id, trial) for _, case_id in case_map for trial in range(1, n_trials + 1)}

    target = _find_latest_job_dir(output_root)
    if target is None:
        timestamp = datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
        target = os.path.join(output_root, "jobs", timestamp)
        os.makedirs(target, exist_ok=True)
        logger.info("[%s] auto-check: no existing job; created %s", harness, target)
    else:
        logger.info("[%s] auto-check: reusing existing job %s", harness, target)

    done = _scan_done_trials(target, case_map, n_trials)
    missing = sorted(expected - done)
    logger.info(
        "[%s] auto-check: %d/%d trial(s) already present; %d missing",
        harness, len(done), len(expected), len(missing),
    )

    if missing:
        id_to_file = {case_id: case_file for case_file, case_id in case_map}
        to_run = [(id_to_file[case_id], trial) for case_id, trial in missing]
        new_results = asyncio.run(
            run_selected(
                to_run,
                experiment.user_proxy,
                server_config,
                target,
                n_trials,
                experiment.concurrency,
            )
        )
        server_info = {
            "harness": harness,
            "model": experiment.model,
            **fetch_server_info(server_config.url),
        }
        all_results = _reconstruct_done_results(target, done) + new_results
        save_runs_summary(all_results, target, n_trials, server_info=server_info)

        new_success = sum(1 for result in new_results if result.status == "success")
        logger.info(
            "[%s] auto-check: ran %d missing trial(s), %d succeeded",
            harness, len(new_results), new_success,
        )
        for result in new_results:
            if result.status == "failed":
                logger.info(
                    "  FAIL %s (trial %d): %s",
                    result.sample_id, result.trial_id, result.error,
                )
    else:
        logger.info("[%s] auto-check: nothing to run; all trials present", harness)

    still_missing = sorted(expected - _scan_done_trials(target, case_map, n_trials))
    if still_missing:
        logger.warning(
            "[%s] auto-check: %d trial(s) STILL missing after run:",
            harness, len(still_missing),
        )
        for case_id, trial in still_missing:
            logger.warning("    MISSING %s trial %d", case_id, trial)
    else:
        logger.info(
            "[%s] auto-check: all %d trial(s) present; proceeding to eval",
            harness, len(expected),
        )

    eval_phase(target, experiment.judge, n_trials, experiment.concurrency)
    logger.info("[%s] done. Results in %s", harness, target)
