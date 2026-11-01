#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

uv_bin = Path.home() / ".local" / "bin" / "uv"
if not uv_bin.exists():
    subprocess.run("curl -LsSf https://astral.sh/uv/install.sh | sh",
                   shell=True, capture_output=True, timeout=60)
    os.environ["PATH"] = f"{Path.home()}/.local/bin:{os.environ.get('PATH', '')}"

agent_dir = Path.home() / ".prime" / "agent"
agent_dir.mkdir(parents=True, exist_ok=True)
(agent_dir / "models.json").write_text(json.dumps({
    "providers": {"openai": {
        "baseUrl": f"{proxy_base}/v1", "api": "openai-completions",
        "apiKey": api_key, "models": [{"id": model}],
    }}
}))
auth = agent_dir / "auth.json"
if not auth.exists():
    auth.write_text(json.dumps({"openai": {"apiKey": api_key, "baseUrl": f"{proxy_base}/v1"}}))

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
