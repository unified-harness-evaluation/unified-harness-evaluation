#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

model = os.environ["HARNESS_MODEL"]

cfg_dir = Path.home() / ".qwen"
cfg_dir.mkdir(parents=True, exist_ok=True)
(cfg_dir / "settings.json").write_text(json.dumps({
    "security": {"auth": {"selectedType": "openai"}}, "selectedModel": model,
}))
wasm_src = Path("/usr/local/lib/node_modules/@qwen-code/qwen-code/node_modules/tiktoken/tiktoken_bg.wasm")
wasm_dst = Path("/usr/local/lib/node_modules/@qwen-code/qwen-code/bundle/tiktoken_bg.wasm")
if wasm_src.exists() and not wasm_dst.exists():
    os.symlink(str(wasm_src), str(wasm_dst))

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
