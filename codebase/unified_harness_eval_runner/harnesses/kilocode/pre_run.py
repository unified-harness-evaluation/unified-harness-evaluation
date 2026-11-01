#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

cfg_dir = Path.home() / ".local" / "share" / "kilo"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "auth.json").write_text(json.dumps(
    {"openai": {"type": "api", "key": api_key, "metadata": {"baseURL": f"{proxy_base}/v1"}}}))
kcfg = Path.home() / ".config" / "kilo"
kcfg.mkdir(parents=True, exist_ok=True)
(kcfg / "kilo.jsonc").write_text(json.dumps(
    {"provider": {"openai": {
        "options": {"baseURL": f"{proxy_base}/v1"},
        "models": {model: {"name": model, "maxTokens": 16384, "contextWindow": 200000}},
    }}}))

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
