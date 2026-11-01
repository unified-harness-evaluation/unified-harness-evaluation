#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
api_key = os.environ["HARNESS_API_KEY"]

cfg_dir = Path.home() / ".codewhale"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "settings.json").write_text(json.dumps({"permissions": {"allow": ["*"], "deny": []}}))
(cfg_dir / "config.toml").write_text(
    f'[providers.openai]\napi_key = "{api_key}"\napi_key_env = "OPENAI_API_KEY"\n'
    f'base_url = "{proxy_base}/v1"\nallow_insecure_http = true\nsend_credentials_to_custom_url = true\n')
os.environ["CODEWHALE_ALLOW_INSECURE_HTTP"] = "1"

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
