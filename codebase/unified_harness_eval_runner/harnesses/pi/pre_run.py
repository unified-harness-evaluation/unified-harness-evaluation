#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

pi_dir = Path.home() / ".pi" / "agent"
pi_dir.mkdir(parents=True, exist_ok=True)
(pi_dir / "models.json").write_text(json.dumps({
    "providers": {"litellm": {
        "baseUrl": f"{proxy_base}/v1", "api": "openai-completions",
        "apiKey": api_key, "models": [{"id": model}],
    }}
}))

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
