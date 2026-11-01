# Harness Evaluation — Paper Artifacts

Reproducibility bundle for the paper: evaluation harness code, test cases,
skills, environment, and the full run logs.

## Layout

| Folder         | What it is |
|----------------|------------|
| `codebase/`    | Evaluation harness source code (the `unified_harness_eval_runner`). |
| `test_cases/`  | Eval inputs — one YAML per case, split into `baseline_split/`, `scenario_1_normal/`, `scenario_2_contradict/`, `scenario_3_policy/`. |
| `skills/`      | Agent skills used in the experiments: `OfficeBench`, `state-shopping`, `state-travel`, `state-customer-support`, `tau2Airline`, `tau2Retail`, `toolsandbox-assistant`. |
| `env/`         | Unified environment for the harness runner: `workspace/` + `testbed/` templates and the `world.db` (SQLite) world database. |
| `results/`     | Aggregated metrics, tables, and figures derived from the logs (per-model `harness_scores_*`). |

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
