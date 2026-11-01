# Benchmarking Agent Harnesses Memory Mechanism on Long-Horizon Enterprise Workflows

Reproducibility bundle for the paper: evaluation harness code, test cases,
skills, environment, and the full run logs.

## Layout

| Folder         | What it is |
|----------------|------------|
| `codebase/`    | Evaluation harness source code (the `unified_harness_eval_runner`). |
| `test_cases/`  | Eval inputs — one YAML per case, split into `baseline_split/`, `scenario_1_normal/`, `scenario_2_contradict/`, `scenario_3_policy/`. |
| `skills/`      | Agent skills used in the experiments: `OfficeBench`, `state-shopping`, `state-travel`, `state-customer-support`, `tau2Airline`, `tau2Retail`, `toolsandbox-assistant`. |
| `env/`         | Unified environment for the harness runner: `workspace/` + `testbed/` templates and the `world.db` (SQLite) world database. |
| `results/`     | Aggregated metrics, tables, and figures derived from the logs (per-model `harness_scores_*`), plus the interactive [behavior-analysis site](results/behavior_analysis_by_cc/) (see below). |
| `logs/`        | Full raw run logs (traces, conversations, usage, per-trial eval results). **Not stored in git** — download from the [GitHub Release](../../releases/tag/logs-v1) (see the Artifacts section). |

## Conditions

All conditions share the same underlying long tasks. The **baseline** test cases
are long tasks with **no memory traps**. We use the capability chain of these
baseline test cases to build the three scenarios, inserting memory traps into
the chain:

| Condition               | Description |
|-------------------------|-------------|
| baseline                | Long task, no memory traps. Defines the capability chain the scenarios build on. |
| scenario_1_normal       | Normal/relevant memory traps inserted into the capability chain. |
| scenario_2_contradict   | Contradicted memory traps inserted into the capability chain. |
| scenario_3_policy       | Policy-related memory traps inserted into the capability chain. |

## Artifacts

Two artifacts are hosted outside the git tree because of their size: the
interactive behavior-analysis site (served via GitHub Pages) and the full raw
run logs (attached to a GitHub Release).

### Behavior-analysis site

An interactive, browsable report of agent memory-behavior analysis is published
via GitHub Pages:

**🔗 https://unified-harness-evaluation.github.io/unified-harness-evaluation/**

It covers **4 harnesses** (`goose`, `grok-build`, `kilocode`, `mistral-vibe`)
× **4 scenarios** (`baseline`, `normal`, `contradict`, `policy`), with one
per-test-case report page each, plus an aggregate overview (tag distributions,
recall modes, memory-credit, and figures).

The source lives in [`results/behavior_analysis_by_cc/`](results/behavior_analysis_by_cc/)
and can also be opened locally by opening `index.html` in a browser:

| Path | What it is |
|------|------------|
| `index.html` | Entry point — links to every report and the aggregate section. |
| `<harness>/<scenario>/<case>.html` | Per-test-case behavior report (with a `.skeleton.json` data sidecar). |
| `_aggregate/OVERVIEW.md` | Written summary of the cross-harness findings. |
| `_aggregate/*.csv` | Aggregated tables (tags by group, components by kind, recall modes, memory credit). |
| `_aggregate/figures/` | Publication figures (PNG + PDF). |


### Run logs

The full raw run logs are **~5.9 GB uncompressed** and are therefore distributed
as a compressed archive attached to a GitHub Release rather than committed to the
repository.

- **Download:** [`logs.tar.gz`](../../releases/download/logs-v1/logs.tar.gz) (~976 MB) from the [`logs-v1` release](../../releases/tag/logs-v1).
- **Extract:** `tar -xzf logs.tar.gz` — this recreates the `logs/` directory at the repo root.

Layout:

```
logs/
└── <model>/                         # DeepSeek-V4-Flash, claude-opus-4.6, gpt-5.6-sol, grok-4.6, kimi-k2.6
    └── <condition>/                 # baseline, scenario_1_normal, scenario_2_contradict, scenario_3_policy
        └── <agent-harness>/         # e.g. deepseek harness, codex, goose, grok-build, hermes-agent, pi, qwen-code, …
            └── <tc_lh_XXXXXXXX>/     # one directory per test case (scenario cases carry a suffix, e.g. _memory, _contradict, _policy)
                └── trial_N/          # one per repeated trial
                    ├── conversation.json          # full agent conversation
                    ├── trace_<uuid>.json          # execution trace
                    ├── usage.json                 # token / tool usage
                    ├── tc_lh_XXXXXXXX.yaml         # the test case that was run
                    └── eval_traceless_<ts>/
                        └── eval_results.json      # per-trial evaluation result
```

Which `<agent-harness>` directories are present varies by model — `claude-opus-4.6`
was run across the full harness set (18 harnesses); the other models cover a
subset. The aggregated scores in [`results/`](results/) are derived from these logs.

