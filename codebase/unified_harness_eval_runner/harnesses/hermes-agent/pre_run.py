#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

cfg_dir = Path.home() / ".hermes"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "config.yaml").write_text(
    f"model: {model}\nmax_turns: 10\nmax_tokens: 4096\n"
    f"providers:\n  proxy:\n    api: {proxy_base}/v1\n    key_env: OPENAI_API_KEY\n")
(cfg_dir / ".env").write_text(f"OPENAI_API_KEY={api_key}\nOPENAI_BASE_URL={proxy_base}/v1\n")

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
