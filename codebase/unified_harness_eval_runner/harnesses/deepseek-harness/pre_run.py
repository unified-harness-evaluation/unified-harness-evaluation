#!/usr/bin/env python3
import os
import sys
from pathlib import Path

proxy_base = os.environ["HARNESS_PROXY_BASE"]
model = os.environ["HARNESS_MODEL"]
api_key = os.environ["HARNESS_API_KEY"]

Path("/workspace/.dsh-proxy.yml").write_text(
    f'- id: llm-deepseek\n  config:\n'
    f'    baseURL: "{proxy_base}/v1"\n'
    f'    thinking: disabled\n'
    f'    maxTokens: 16384\n'
    f'    models:\n'
    f'      - id: {model}\n'
    f'        name: {model}\n'
    f'        contextWindow: 200000\n'
    f'- id: agent-default-model\n  config:\n'
    f'    provider: deepseek-official\n'
    f'    model: {model}\n')
os.environ["DEEPSEEK_API_KEY"] = api_key

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
