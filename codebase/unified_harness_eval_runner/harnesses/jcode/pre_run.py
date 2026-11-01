#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]

proxy_host_port = urlparse(proxy_base).port or 8000
local_port = 4000
subprocess.Popen(["socat", f"TCP-LISTEN:{local_port},fork,reuseaddr",
                  f"TCP:host.docker.internal:{proxy_host_port}"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.5)

jcode_dir = Path.home() / ".jcode"
jcode_dir.mkdir(parents=True, exist_ok=True)
(jcode_dir / "config.toml").write_text(
    f'[provider]\ndefault_provider = "proxy"\ndefault_model = "{model}"\n\n'
    f'[providers.proxy]\ntype = "openai-compatible"\n'
    f'base_url = "http://localhost:{local_port}/v1"\nauth = "bearer"\n'
    f'api_key_env = "JCODE_PROXY_API_KEY"\ndefault_model = "{model}"\n'
    f'requires_api_key = true\n\n'
    f'[[providers.proxy.models]]\nid = "{model}"\ncontext_window = 128000\n')

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
