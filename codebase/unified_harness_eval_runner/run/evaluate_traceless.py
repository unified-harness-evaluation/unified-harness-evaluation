"""Traceless eval runner: subgoal progress from the agent–user dialogue only.

A stripped-down sibling of :mod:`experiment_clean.evaluate`. It scores subgoal
completion using ONLY ``conversation.json`` (the agent–user dialogue) — no trace
conversion, no tool-call steps. Because the turn traces carry empty ``steps``,
``SubGoalCompletionValidator.validate_dynamic`` automatically selects its NO_STEPS
judge template and grades on the dialogue alone.

Token / latency: these never appear in conversation.json. The gateway counts
them per trial (the container authenticates to the /v1 proxy with a per-trial
key), conversation.py writes them to ``usage.json`` in the trial folder, and we
fold the totals into ``AgentDialogueTrace.metadata``. When usage.json is
absent, both totals are reported as ``None``.

Metrics dropped vs. evaluate.py: pass@k / pass^k, skill precision/recall,
capability score, tool_call_count.

Usage:
    # Single trial
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.evaluate_traceless \\
        experiment_clean/experiment_results/jobs/<job>/tc_foo/trial_1/ --n-trials 5

    # Whole job
    PYTHONPATH="agent-inspect/src:." python -m experiment_clean.evaluate_traceless \\
        experiment_clean/experiment_results/jobs/<job>/ --n-trials 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_inspect.metrics.validator import SubGoalCompletionValidator
from agent_inspect.metrics.scorer import ProgressScore
from agent_quality_inspect.efficiency import EfficiencyMetric
from agent_quality_inspect.templates import (
    DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_NO_STEPS_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL,
)
from agent_inspect.metrics.constants import (
    INCLUDE_JUDGE_EXPLANATION,
    INCLUDE_VALIDATION_RESULTS,
    INCLUDE_PROMPT_SENT_TO_LLMJ,
    OPTIMIZE_JUDGE_TRIALS,
    TEMPLATE_SUBGOAL,
    NUM_JUDGE_TRIALS,
)
from agent_inspect.models.metrics.agent_trace import (
    AgentDialogueTrace,
    AgentResponse,
    TurnTrace,
)
from agent_quality_inspect.litellm_client import LiteLLMClient

#    experiment_clean.X -> flat imports, trace_converter guarded ──
from config import (
    DEFAULT_RUNNER_CONFIG,
    JudgeConfig,
    load_experiment,
    silence_litellm,
    parse_test_case,
)
from run.efficiency_metric_helper import efficiency_per_turn, efficiency_per_llm_calls

silence_litellm()

logger = logging.getLogger("evaluate_traceless")


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class TrialEvalResult:
    trial_id: int
    sample_id: str
    status: str = "success"
    error: Optional[str] = None
    total_turns: int = 0
    metrics: Optional[Dict[str, Any]] = None

    @property
    def final_progress(self) -> Optional[float]:
        rates = (self.metrics or {}).get("progress_rates", [])
        return rates[-1] if rates else None

    @property
    def final_memory_progress(self) -> Optional[float]:
        rates = (self.metrics or {}).get("memory_progress_rates", [])
        return rates[-1] if rates else None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "trial_id": self.trial_id,
            "sample_id": self.sample_id,
            "status": self.status,
            "total_turns": self.total_turns,
        }
        if self.error:
            out["error"] = self.error
        if self.metrics:
            out["metrics"] = self.metrics
        return out


# ── Folder detection ─────────────────────────────────────────────────────────

def discover_trial_folders(root: Path) -> List[Path]:
    """Find all trial folders (contain conversation.json) under root."""
    return sorted(p.parent for p in root.rglob("conversation.json"))


def _is_trial_folder(path: Path) -> bool:
    return (path / "conversation.json").exists()


# ── Dialogue turns from conversation.json ─────────────────────────────────────

def load_dialogue_turns(conv_path: Path) -> AgentDialogueTrace:
    """Build dialogue-only turn traces from conversation.json.

    Each conversation entry becomes a :class:`TurnTrace` with the user message as
    ``agent_input`` and the agent's final response as ``agent_response``. Steps
    are left empty so the subgoal judge grades on the dialogue alone.
    """
    conv = json.loads(conv_path.read_text())
    turns: List[TurnTrace] = []

    for i, c in enumerate(conv.get("conversations") or []):
        user_message = c.get("user_message") or {}
        agent_input = user_message.get("message_str", "") or ""

        # Take the last non-empty agent response for this turn.
        response_str: Optional[str] = None
        for a in c.get("agent_responses") or []:
            if a.get("response_str"):
                response_str = a["response_str"]

        agent_response = (
            AgentResponse(response=response_str) if response_str is not None else None
        )

        turns.append(TurnTrace(
            id=str(c.get("id", i)),
            agent_input=agent_input,
            agent_response=agent_response,
            steps=[],
        ))

    trace = AgentDialogueTrace(turns=turns)
    trace.metadata = {}
    return trace


# ── Token / latency from usage.json ──────────────────────────────────────────

def enrich_with_usage(trace: AgentDialogueTrace, trial_folder: Path) -> Dict[str, Optional[float]]:
    """Fold the trial's usage.json (written by conversation.py from the server's
    per-trial LLM-usage accounting) into the dialogue trace metadata. Returns
    token/latency totals, or ``None`` for both when usage.json is absent.
    """
    usage_path = trial_folder / "usage.json"
    if not usage_path.exists():
        logger.warning("No usage.json in %s — tokens/latency unavailable", trial_folder)
        return {"total_tokens": None, "total_latency_ms": None}

    usage = json.loads(usage_path.read_text())
    total_tokens = usage.get("total_tokens")
    # Wall-clock time of the agent turns, start to finish, summed over turns.
    total_latency_ms = usage.get("turn_latency_ms")

    trace.metadata = {
        "total_token_consumption": total_tokens,
        "total_latency_ms": total_latency_ms,
        "usage": usage,
    }
    return {"total_tokens": total_tokens, "total_latency_ms": total_latency_ms}


# ── Core evaluation ──────────────────────────────────────────────────────────

async def evaluate_trial(trial_folder: Path, judge: JudgeConfig) -> dict:
    """Run the subgoal metric on a single trial from its dialogue. Returns metrics dict."""
    trial_folder = Path(trial_folder)

    conv_path = trial_folder / "conversation.json"
    if not conv_path.exists():
        raise FileNotFoundError(f"No conversation.json in {trial_folder}")
    trace = load_dialogue_turns(conv_path)

    # Parse test case — exactly one YAML per trial folder
    yaml_files = sorted(trial_folder.glob("*.yaml"))
    if len(yaml_files) != 1:
        raise ValueError(
            f"Expected exactly 1 .yaml in {trial_folder}, found {len(yaml_files)}: {yaml_files}"
        )
    criteria = parse_test_case(str(yaml_files[0]))

    if judge.api_key:
        os.environ.setdefault("AZURE_AI_API_KEY", judge.api_key)
    if judge.api_base:
        os.environ.setdefault("AZURE_AI_API_BASE", judge.api_base)
    llm_client = LiteLLMClient(model=judge.model, max_tokens=judge.max_tokens)

    # ── Subgoal progress (dialogue-only) ─────────────────────────────────
    validator_config = {
        INCLUDE_VALIDATION_RESULTS: True,
        INCLUDE_JUDGE_EXPLANATION: True,
        INCLUDE_PROMPT_SENT_TO_LLMJ: True,
        OPTIMIZE_JUDGE_TRIALS: False,
        TEMPLATE_SUBGOAL: DEFAULT_MODEL_GRADED_FACT_DYNAMIC_SUMMARY_NO_STEPS_REMOVE_HALLUCINATION_CHECK_TEMPLATE_ONE_SUBGOAL,
        NUM_JUDGE_TRIALS: judge.num_judge_trials,
    }
    goal_validator = SubGoalCompletionValidator(
        llm_client=llm_client, config=validator_config,
    )
    validation_results = await asyncio.gather(*[
        goal_validator.validate_dynamic(
            turn_traces=trace.turns,
            sub_goal=sg,
            user_instruction=criteria.task_summary,
        )
        for sg in criteria.sub_goals
    ])
    progress_score = ProgressScore.get_progress_score_from_validation_results(
        list(validation_results)
    )

    # ── Memory-based subgoal progress (same validator, separate score) ────
    # Graded by the same SubGoalCompletionValidator but kept apart so the memory
    # score never mixes into the normal progress rate. When a test case has no
    # memory_agent_response_validations, the rate degrades to None.
    memory_validation_results = await asyncio.gather(*[
        goal_validator.validate_dynamic(
            turn_traces=trace.turns,
            sub_goal=sg,
            user_instruction=criteria.task_summary,
        )
        for sg in criteria.memory_sub_goals
    ])
    memory_progress_rate = (
        ProgressScore.get_progress_score_from_validation_results(
            list(memory_validation_results)
        ).score
        if memory_validation_results
        else None
    )

    # ── Token / latency (from the DB stream_events, folded into the trace) ──
    token_latency = enrich_with_usage(trace, trial_folder)

    # ── Efficiency = progress per unit cost ──────────────────────────────
    # The dialogue-only trace carries empty steps, so neither tokens, turns, nor
    # llm_calls can be read off the trace. Tokens come from usage.json and will use
    # agent-inspect static helper for calculation; turns (= dialogue length) and llm_calls use the
    # local helpers. Each degrades to None when its denominator is zero/absent.
    usage = trace.metadata.get("usage") or {}
    total_tokens = token_latency["total_tokens"]
    num_llm_calls = usage.get("llm_calls")

    token_efficiency = (
        EfficiencyMetric.compute_token_efficiency(progress_score, total_tokens).score
        if total_tokens
        else None
    )
    turn_efficiency = efficiency_per_turn(progress_score.score, len(trace.turns))
    llm_call_efficiency = efficiency_per_llm_calls(progress_score.score, num_llm_calls)

    return {
        "progress_rates": [progress_score.score],
        "subgoal_validations": [
            {
                "is_completed": v.is_completed,
                "details": v.sub_goal.details,
                "explanations": v.explanations,
            }
            for v in validation_results
        ],
        "memory_progress_rates": [memory_progress_rate] if memory_progress_rate is not None else [],
        "memory_subgoal_validations": [
            {
                "is_completed": v.is_completed,
                "details": v.sub_goal.details,
                "explanations": v.explanations,
            }
            for v in memory_validation_results
        ],
        "total_tokens": token_latency["total_tokens"],
        "total_latency_ms": token_latency["total_latency_ms"],
        "token_efficiency": token_efficiency,
        "turn_efficiency": turn_efficiency,
        "llm_call_efficiency": llm_call_efficiency,
    }


# ── Aggregation ──────────────────────────────────────────────────────────────

def aggregate_metrics(
    results: List[TrialEvalResult],
    n_trials: int,
) -> Dict[str, Any]:
    """Aggregate per-trial subgoal metrics into job-level summary."""
    by_sample: Dict[str, List[TrialEvalResult]] = defaultdict(list)
    for r in results:
        if r.status == "success" and r.metrics:
            by_sample[r.sample_id].append(r)

    metrics: Dict[str, Any] = {}

    # Progress rate
    max_pr, mean_pr = {}, {}
    for sid, trs in by_sample.items():
        finals = [t.final_progress for t in trs if t.final_progress is not None]
        max_pr[sid] = max(finals) if finals else None
        mean_pr[sid] = statistics.mean(finals) if finals else None
    valid_max = [v for v in max_pr.values() if v is not None]
    valid_mean = [v for v in mean_pr.values() if v is not None]
    metrics["max_progress_rate"] = {
        "per_sample": max_pr,
        "avg": statistics.mean(valid_max) if valid_max else None,
    }
    metrics["mean_progress_rate"] = {
        "per_sample": mean_pr,
        "avg": statistics.mean(valid_mean) if valid_mean else None,
    }

    # Memory-based subgoal progress rate (independent of the normal rate).
    # Samples without any memory subgoals contribute None and are skipped.
    max_mem, mean_mem = {}, {}
    for sid, trs in by_sample.items():
        finals = [t.final_memory_progress for t in trs if t.final_memory_progress is not None]
        max_mem[sid] = max(finals) if finals else None
        mean_mem[sid] = statistics.mean(finals) if finals else None
    valid_max_mem = [v for v in max_mem.values() if v is not None]
    valid_mean_mem = [v for v in mean_mem.values() if v is not None]
    metrics["max_memory_progress_rate"] = {
        "per_sample": max_mem,
        "avg": statistics.mean(valid_max_mem) if valid_max_mem else None,
    }
    metrics["mean_memory_progress_rate"] = {
        "per_sample": mean_mem,
        "avg": statistics.mean(valid_mean_mem) if valid_mean_mem else None,
    }

    # Scalar metrics (token / latency / efficiency)
    for field in (
        "total_tokens",
        "total_latency_ms",
        "token_efficiency",
        "turn_efficiency",
        "llm_call_efficiency",
    ):
        avg_per_sample = {}
        for sid, trs in by_sample.items():
            vals = [
                t.metrics.get(field)
                for t in trs
                if t.metrics and t.metrics.get(field) is not None
            ]
            avg_per_sample[sid] = statistics.mean(vals) if vals else None
        valid = [v for v in avg_per_sample.values() if v is not None]
        metrics[field] = {
            "per_sample": avg_per_sample,
            "avg": statistics.mean(valid) if valid else None,
        }

    all_by_sample: Dict[str, List[TrialEvalResult]] = defaultdict(list)
    for r in results:
        all_by_sample[r.sample_id].append(r)

    return {"n_samples": len(all_by_sample), "n_trials": n_trials, "metrics": metrics}


# ── Batch eval ───────────────────────────────────────────────────────────────

async def run_eval_batch(
    trial_folders: List[Path],
    judge: JudgeConfig,
    n_trials: int,
    max_workers: int = 4,
    run_ts: Optional[str] = None,
) -> List[TrialEvalResult]:
    """Evaluate all trial folders concurrently."""
    sem = asyncio.Semaphore(max_workers)
    if run_ts is None:
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    async def _eval_one(tf: Path) -> TrialEvalResult:
        try:
            trial_id = int(tf.name.split("_")[-1])
        except ValueError:
            trial_id = 1
        sample_id = tf.parent.name

        async with sem:
            try:
                metrics = await evaluate_trial(tf, judge)
                total_turns = 0
                conv = tf / "conversation.json"
                if conv.exists():
                    total_turns = len(
                        json.loads(conv.read_text()).get("conversations", [])
                    )
                r = TrialEvalResult(
                    trial_id=trial_id, sample_id=sample_id,
                    total_turns=total_turns, metrics=metrics,
                )
                # Print summary
                rates = metrics["progress_rates"]
                logger.info(
                    "\n%s\nCase: %s/%s\nProgress: %.4f\n%s",
                    "=" * 60, sample_id, tf.name,
                    rates[-1] if rates else 0, "=" * 60,
                )
                # Save per-trial eval
                eval_dir = tf / f"eval_traceless_{run_ts}"
                eval_dir.mkdir(exist_ok=True)
                (eval_dir / "eval_results.json").write_text(
                    json.dumps(metrics, indent=2, default=str)
                )
            except Exception as exc:
                logger.error("Eval failed for %s: %s", tf, exc)
                r = TrialEvalResult(
                    trial_id=trial_id, sample_id=sample_id,
                    status="failed", error=str(exc),
                )
        return r

    return list(await asyncio.gather(*[_eval_one(tf) for tf in trial_folders]))


def _write_trial_results(
    results: List[TrialEvalResult], eval_dir: Path
) -> None:
    by_trial: Dict[int, List[TrialEvalResult]] = defaultdict(list)
    for r in results:
        by_trial[r.trial_id].append(r)
    for tid, trs in sorted(by_trial.items()):
        data = {
            "trial_id": tid,
            "total_samples": len(trs),
            "successful": sum(1 for r in trs if r.status == "success"),
            "samples": [r.to_dict() for r in trs],
        }
        (eval_dir / f"trial_{tid}_results.json").write_text(
            json.dumps(data, indent=2, default=str)
        )


def _write_aggregate(
    results: List[TrialEvalResult], n_trials: int, eval_dir: Path
) -> Dict[str, Any]:
    agg = aggregate_metrics(results, n_trials)
    n_samples = agg["n_samples"]
    ok = [r for r in results if r.status == "success"]
    fail = [r for r in results if r.status == "failed"]
    expected_runs = n_samples * n_trials
    missing = expected_runs - len(results)
    summary = {
        "n_samples": n_samples,
        "n_trials": n_trials,
        "expected_runs": expected_runs,
        "successful": len(ok),
        "failed": len(fail),
        "missing": missing,
        "avg_turns": (sum(r.total_turns for r in ok) / len(ok)) if ok else 0,
    }
    output = {"timestamp": datetime.now().isoformat(), "summary": summary, **agg}
    (eval_dir / "aggregate_metrics_results.json").write_text(
        json.dumps(output, indent=2, default=str)
    )
    return agg


def _log_eval_summary(
    results: List[TrialEvalResult],
    n_trials: int,
    aggregated: Dict[str, Any],
) -> None:
    n_samples = aggregated["n_samples"]
    ok = [r for r in results if r.status == "success"]
    fail = [r for r in results if r.status == "failed"]
    expected_runs = n_samples * n_trials
    missing = expected_runs - len(results)
    m = aggregated["metrics"]
    logger.info(
        "\n%s\n%d sample(s) x %d trial(s) = %d expected | %d successful, %d failed, %d missing\n%s"
        "\nMax progress rate  (avg): %s"
        "\nMean progress rate (avg): %s"
        "\nMax memory-based subgoal score  (avg): %s"
        "\nMean memory-based subgoal score (avg): %s"
        "\nAvg total_tokens:     %s"
        "\nAvg total_latency_ms: %s"
        "\nAvg token_efficiency:    %s"
        "\nAvg turn_efficiency:     %s"
        "\nAvg llm_call_efficiency: %s",
        "=" * 70, n_samples, n_trials, expected_runs,
        len(ok), len(fail), missing, "=" * 70,
        _fmt(m["max_progress_rate"]["avg"]),
        _fmt(m["mean_progress_rate"]["avg"]),
        _fmt(m["max_memory_progress_rate"]["avg"]),
        _fmt(m["mean_memory_progress_rate"]["avg"]),
        _fmt(m["total_tokens"]["avg"]),
        _fmt(m["total_latency_ms"]["avg"]),
        _fmt(m["token_efficiency"]["avg"]),
        _fmt(m["turn_efficiency"]["avg"]),
        _fmt(m["llm_call_efficiency"]["avg"]),
    )
    for r in fail:
        logger.info("  FAILED %s (trial %d): %s", r.sample_id, r.trial_id, r.error)


def save_results(
    results: List[TrialEvalResult],
    n_trials: int,
    output_dir: Path,
    run_ts: str,
) -> None:
    eval_dir = output_dir / f"eval_traceless_{run_ts}"
    eval_dir.mkdir(exist_ok=True)
    _write_trial_results(results, eval_dir)
    aggregated = _write_aggregate(results, n_trials, eval_dir)
    _log_eval_summary(results, n_trials, aggregated)


def _fmt(v) -> str:
    return f"{v:.4f}" if isinstance(v, (int, float)) else "n/a"


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CUGA traceless eval runner (subgoal only)")
    parser.add_argument("path", nargs="+",
                        help="Trial/case/job folder(s) — multiple paths are aggregated together")
    parser.add_argument("--n-trials", type=int, required=True,
                        help="Number of trials (must match conversation run)")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--config", default=DEFAULT_RUNNER_CONFIG)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    experiment = load_experiment(args.config)
    judge = experiment.judge
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info(
        "Judge: model=%s  max_tokens=%d  trials=%d",
        judge.model, judge.max_tokens, judge.num_judge_trials,
    )

    # Discover trial folders across all input paths
    trial_folders = []
    for p in args.path:
        root = Path(p)
        if not root.exists():
            print(f"Warning: {root} does not exist, skipping", file=sys.stderr)
            continue
        if _is_trial_folder(root):
            trial_folders.append(root)
        else:
            trial_folders.extend(discover_trial_folders(root))

    if not trial_folders:
        print(f"No trial folders found under {args.path}", file=sys.stderr)
        sys.exit(1)

    logger.info("Found %d trial folder(s) across %d path(s)", len(trial_folders), len(args.path))

    results = asyncio.run(run_eval_batch(
        trial_folders, judge, args.n_trials,
        max_workers=args.max_workers,
        run_ts=run_ts,
    ))

    # Save aggregate results to the first path
    output_root = Path(args.path[0])
    save_results(results, args.n_trials, output_root, run_ts)


if __name__ == "__main__":
    main()
