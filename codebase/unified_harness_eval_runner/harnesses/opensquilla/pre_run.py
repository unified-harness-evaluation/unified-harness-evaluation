#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]
api_base = f"{proxy_base}/v1"

cfg_dir = Path.home() / ".opensquilla"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / ".env").write_text(
    f"OPENAI_API_KEY={api_key}\nOPENAI_API_BASE={api_base}\nOPENSQUILLA_LOG_LEVEL=WARNING\n")
(cfg_dir / "config.toml").write_text(
    f'[llm]\nprovider = "openai"\napi_key = "{api_key}"\nbase_url = "{api_base}"\nmodel = "{model}"\n')

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
