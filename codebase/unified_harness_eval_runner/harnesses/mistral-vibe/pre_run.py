#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]

cfg_dir = Path.home() / ".vibe"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "config.toml").write_text(
    f'active_model = "{model}"\ndefault_agent = "auto-approve"\nenable_telemetry = false\n\n'
    f'[[providers]]\nname = "proxy"\napi_base = "{proxy_base}/v1"\n'
    f'api_key_env_var = "MISTRAL_API_KEY"\napi_style = "openai"\nemits_finish_reason = false\n\n'
    f'[[models]]\nname = "{model}"\nprovider = "proxy"\n')

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
