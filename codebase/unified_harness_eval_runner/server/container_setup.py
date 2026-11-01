#!/usr/bin/env python3
"""Shared setup helpers, imported by each harness's pre_run.py inside the container."""

import os
import sys
from pathlib import Path


def finalize_workspace():
    """Git-init /workspace if git is available, then copy skills from the env var."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        # Minimal images ship without git. The traceless
        # judge scores the dialogue, not a workspace diff, so skip the init.
        print(
            "WARN: git not found in container; skipping /workspace git init",
            file=sys.stderr,
        )
    elif not Path("/workspace/.git").exists():
        subprocess.run(["git", "init", "/workspace"], capture_output=True)
        subprocess.run(
            ["git", "-C", "/workspace", "config", "user.email", "eval@test"],
            capture_output=True,
        )

    skills_csv = os.environ.get("HARNESS_SKILLS_DIRS", "")
    if skills_csv:
        copy_skills([d for d in skills_csv.split(",") if d])


def copy_skills(skills_dirs):
    import shutil

    skills_src = next(
        (
            Path(candidate)
            for candidate in (
                "/workspace/.pi/skills",
                "/workspace/skills",
                "/home/agent/workspace/.pi/skills",
                "/home/agent/workspace/skills",
            )
            if Path(candidate).is_dir()
        ),
        None,
    )
    if skills_src is None:
        print(
            "WARN: no skills source found in "
            "/workspace/.pi/skills or /workspace/skills",
            file=sys.stderr,
        )
        return
    try:
        contents = list(skills_src.iterdir())
        if not contents:
            print(f"WARN: skills source {skills_src} is empty", file=sys.stderr)
            return
    except OSError as exc:
        print(f"WARN: cannot read skills source {skills_src}: {exc}", file=sys.stderr)
        return

    print(f"skills source: {skills_src} ({len(contents)} items)", file=sys.stderr)

    copied = 0
    for target in skills_dirs:
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = Path("/workspace") / target
        if target_path.exists():
            if target_path.resolve() == skills_src.resolve():
                continue
            existing = list(target_path.iterdir()) if target_path.is_dir() else []
            print(
                f"skills target {target_path} already exists "
                f"({len(existing)} items), replacing",
                file=sys.stderr,
            )
            shutil.rmtree(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skills_src, target_path)
        result = list(target_path.iterdir())
        print(f"copied {len(result)} skill items to {target_path}", file=sys.stderr)
        copied += 1
    if copied == 0 and skills_dirs:
        print(f"ERROR: no skills were copied to any of {skills_dirs}", file=sys.stderr)
        sys.exit(1)
