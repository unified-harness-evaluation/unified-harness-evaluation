#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

Path("/workspace/opencode.json").write_text(json.dumps({
    "$schema": "https://opencode.ai/config.json",
    "provider": {"proxy": {
        "npm": "@ai-sdk/openai-compatible", "name": "Proxy",
        "options": {"baseURL": f"{proxy_base}/v1", "apiKey": api_key},
        "models": {model: {"name": model}},
    }},
}))

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
