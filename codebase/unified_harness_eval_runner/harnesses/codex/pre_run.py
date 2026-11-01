#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]

cfg_dir = Path.home() / ".codex"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "config.toml").write_text(
    f'model = "{model}"\nmodel_provider = "openai-proxy"\n\n'
    f'[model_providers.openai-proxy]\nname = "openai-proxy"\n'
    f'base_url = "{proxy_base}/v1"\nwire_api = "responses"\n'
    f'env_key = "OPENAI_API_KEY"\nsupports_websockets = false\n')

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
