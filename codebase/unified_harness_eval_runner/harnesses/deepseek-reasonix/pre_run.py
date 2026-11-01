#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

cfg_dir = Path.home() / ".config" / "reasonix"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "reasonix.toml").write_text(
    f'[[providers]]\nname = "openai-proxy"\nkind = "openai"\n'
    f'base_url = "{proxy_base}/v1"\napi_key_env = "OPENAI_API_KEY"\nmodel = "{model}"\n'
    f'\n[sandbox]\nbash = "off"\n')
env_dir = Path.home() / ".reasonix"
env_dir.mkdir(parents=True, exist_ok=True)
(env_dir / ".env").write_text(f"OPENAI_API_KEY={api_key}\n")

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
