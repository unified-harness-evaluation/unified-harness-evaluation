#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

grok_dir = Path.home() / ".grok"
grok_dir.mkdir(parents=True, exist_ok=True)
(grok_dir / "config.toml").write_text(
    f'[cli]\ninstaller = "npm"\n\n[model.proxy]\nmodel = "{model}"\n'
    f'base_url = "{proxy_base}/v1"\napi_key = "{api_key}"\n'
    f'api_backend = "chat_completions"\nname = "proxy"\n')
(grok_dir / "auth.json").write_text(json.dumps({
    "accessToken": api_key, "refreshToken": "none",
    "expiresAt": "2099-01-01T00:00:00.000Z", "provider": "xai",
}))
os.environ["XAI_API_KEY"] = api_key

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
