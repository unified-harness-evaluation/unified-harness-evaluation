#!/usr/bin/env python3
"""Strip goose CLI noise from turn output."""
import re


def strip(output, skill_lines=frozenset()):
    output = re.sub(r'\x1b\[[0-9;]*m', '', output)
    lines = []
    skip_args = False
    for line in output.splitlines():
        s = line.strip()
        if (s.startswith("─────") or s.startswith("__( O)>")
                or s.startswith("\\____") or s.startswith("L L")):
            continue
        if s.startswith("▸ "):
            skip_args = True
            continue
        if skip_args and (s.startswith("path ") or s.startswith("content:")
                          or s.startswith("command:") or s.startswith("todo")
                          or s.startswith("name:") or not s):
            continue
        skip_args = False
        if re.match(r'^# Loaded Skill: \S+ \(skill\)$', s) or s == "## Content":
            continue
        if skill_lines and s in skill_lines:
            continue
        s = re.sub(r'^Created \S+ \(\d+ lines?\)', '', s)
        s = re.sub(r'^\(no output\)', '', s).strip()
        if s:
            lines.append(s)
    output = "\n".join(lines)
    output = re.sub(r'<\|[^|]+\|>', '', output)
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines).strip()
