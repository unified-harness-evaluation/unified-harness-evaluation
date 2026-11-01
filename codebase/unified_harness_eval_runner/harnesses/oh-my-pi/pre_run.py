#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

agent_dir = Path.home() / ".omp" / "agent"
agent_dir.mkdir(parents=True, exist_ok=True)
(agent_dir / "models.yml").write_text(
    f"providers:\n  openai:\n    baseUrl: {proxy_base}/v1\n"
    f"    api: openai-completions\n    apiKey: {api_key}\n"
    f"    models:\n      - id: {model}\n")

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
