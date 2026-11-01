# unified_harness_eval

Traceless evaluation of coding agents. Each agent runs in its own
Docker container, holds a multi-turn conversation with an LLM-driven user
proxy, and a judge grades the transcript afterwards. The judge sees only the
dialogue, never the agent's internal tool calls or reasoning.

## Setup

1. Create the virtual environment and install dependencies:

```bash
uv venv
uv pip install -r requirements.txt
```

This installs [`agent-quality-inspect`](https://pypi.org/project/agent-quality-inspect/)
(the open-source evaluation library) automatically via `requirements.txt`.

2. Install the local compatibility shim (provides overrides for components not
yet shipped in the open-source release):

```bash
uv pip install -e agent-quality-inspect/
```

3. Prepare the test cases, skills, and environment. These live at the project
root (two levels up from this runner, i.e. `../../`):

- **Test cases** are in `test_cases/`, split into `baseline_split/`,
  `scenario_1_normal/`, `scenario_2_contradict/`, and `scenario_3_policy/`.
  Point `run.tests` in `runner_config.yaml` at the directory (or a single
  `tc_*.yaml` file).
- **Skills** are in `skills/` (`OfficeBench`, `state-shopping`, `tau2Airline`,
  `toolsandbox-assistant`, ...). Set `skills.path` to this directory, or leave
  it unset to auto-detect from the environment's `.pi/skills` / `skills/`.
- **Environment** is in `env/`: the `workspace/` and `testbed/` templates
  bind-mounted into `/workspace`, plus the unified world database `env/world.db`
  (SQLite) that backs the stateful skills. Set `run.workspace` to `env/`.

4. Create config files:

```bash
cp runner_config.yaml.example runner_config.yaml
cp .env.example .env          # fill in AZURE_API_KEY, AZURE_API_BASE
```

Pass in the correct API key credentials and configure `runner_config.yaml`.

5. Build the Docker image(s) for the harness(es) you want to evaluate:

```bash
./build.sh                      # all harnesses
./build.sh pi codex             # only the named ones
```

See `runner_config.yaml.example` for all available options.

## Run

```bash
source .env

# run litellm server on the backend
litellm --config litellm_azure_config.yaml --port 4001 &

python3 -m e2e                       # run with default runner_config.yaml
python3 -m e2e --config other.yaml   # run with a custom config
```

Switch the agent model by setting `agent.model` in your runner config to any
`model_name` in `litellm_azure_config.yaml`: `claude-opus-4-6`, `gpt-5.4`,
`gpt-5.6-sol`, `Kimi-K2.6`, `DeepSeek-V4-Flash`, `grok-4.6`.

Retry only the failed trials of a previous run, then re-judge:

```bash
python3 -m e2e --resume <results_dir>/<harness>/jobs/<timestamp>
```

Resume reads harness, model and trial count from the job's
`runs_summary.json` and starts its own gateway if none is running.

Fill in only the trials still missing from the latest job of each harness
(skipping cases already run), re-check completeness, then judge:

```bash
python3 -m e2e --auto-check-run-missing
```

This reuses each harness's most recent `jobs/<timestamp>` directory (creating
one if none exists), and then based on the test cases runs the missing `(case, trial)` combinations.
After all are collected, start the evaluation.

## Reading results

Per harness job directory:

- `tc_<case>/trial_<n>/conversation.json` -- the full dialogue
- `eval_traceless_<ts>/aggregate_metrics_results.json` -- judge scores
- `runs_summary.json` -- trial statuses, used by `--resume`

## Harness configuration

Each harness lives in `harnesses/<name>/harness.yaml`. Required fields:

- `image` -- Docker image name
- `turn_mode` -- how the eval talks to the agent: `cli` (docker exec per turn)
  or `http` (long-lived server with JSON-RPC calls)

CLI harnesses (`turn_mode: cli`) also need `cmd` (the command template with
`{model}`, `{task}`, `{api_key}`, `{proxy_base}` placeholders).

HTTP harnesses (`turn_mode: http`) need an `http_server` block with `port`,
`health` (health-check path), and `path` (the JSON-RPC endpoint).

## Module layout

```
e2e.py                         Entry point: starts gateway, loops harnesses, runs eval

config/
  config.py                    Typed config dataclasses (Experiment, ServerConfig, ...), YAML loading
  testcase.py                  Test case YAML parsing, evaluation criteria (SubGoal, SkillCall, ...)

server/
  __init__.py                  HarnessError exception (shared by server and turn packages)
  harness_server.py            Multi-tenant FastAPI gateway, session management
  container.py                 Docker container wrapper + harness lifecycle (open/ask/close)
  container_setup.py           Runs inside containers: git init + skills copy

turn/
  turn_cli.py                  CLI turn execution via docker exec
  turn_http.py                 HTTP turn execution via A2A JSON-RPC

run/
  conversation.py              Per-trial conversation loop, TrialResult, session management
  efficiency_metric_helper.py  Efficiency scores (per turn / per LLM call) from raw counts
  evaluate_traceless.py        Traceless subgoal judge
  user_proxy.py                LLM-driven user simulation
  trace.py                     Trace types (AgentTrace, Step, ...) and serialization

agent-quality-inspect/
  src/agent_quality_inspect/   Compatibility overrides for components absent from the PyPI release:
    litellm_client.py            LiteLLMClient implementation
    efficiency.py                EfficiencyMetric class
    templates.py                 NO_STEPS judge prompt template
    constants.py                 Efficiency-related constants
  tests/                       Unit tests for the above overrides
```

