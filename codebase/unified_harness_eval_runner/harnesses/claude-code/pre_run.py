#!/usr/bin/env python3
"""Pre-run setup for the official Anthropic Claude Code harness.

Claude Code refuses to run with ``--dangerously-skip-permissions`` as root, so
the agent runs as the non-root ``coder`` user (see harness.yaml cmd
``runuser -u coder -- claude ...`` with ``HOME=/home/coder``). We seed coder's
config so the CLI starts non-interactively: permissions allow-all, and the
first-run onboarding / trust prompts pre-answered in ``~/.claude.json``.
"""
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
claude_dir = coder_home / ".claude"
claude_dir.mkdir(parents=True, exist_ok=True)

# Permissions: allow everything (we also pass --dangerously-skip-permissions).
(claude_dir / "settings.json").write_text(json.dumps({
    "permissions": {"allow": ["*"], "deny": []},
    "allowDangerouslySkipPermissions": True,
}))

# Pre-answer first-run onboarding/theme/trust so the CLI never blocks on a
# prompt in non-interactive (-p) mode. hasTrustDialogAccepted is keyed per
# project dir; /workspace is where the agent runs.
(coder_home / ".claude.json").write_text(json.dumps({
    "hasCompletedOnboarding": True,
    "bypassPermissionsModeAccepted": True,
    "theme": "dark",
    "projects": {
        "/workspace": {
            "hasTrustDialogAccepted": True,
            "hasCompletedProjectOnboarding": True,
            "allowedTools": ["*"],
        }
    },
}))

Path("/workspace").mkdir(exist_ok=True)
subprocess.run(["chown", "-R", "coder:coder", str(coder_home), "/workspace"],
               check=False)

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
