#!/usr/bin/env python3
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

try:
    pwd.getpwnam("coder")
except KeyError:
    subprocess.run(["useradd", "-m", "-s", "/bin/bash", "coder"], check=True)
coder_home = Path("/home/coder")
claude_dir = coder_home / ".openclaude"
claude_dir.mkdir(parents=True, exist_ok=True)
(claude_dir / "settings.json").write_text(json.dumps({
    "permissions": {"allow": ["*"], "deny": []},
    "allowDangerouslySkipPermissions": True,
}))
subprocess.run(["chown", "-R", "coder:coder", "/home/coder", "/workspace"],
               capture_output=True)
Path("/workspace").mkdir(exist_ok=True)
subprocess.run(["chown", "-R", "coder:coder", str(coder_home), "/workspace"], check=False)

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
