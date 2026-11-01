#!/usr/bin/env python3
"""Strip hermes-agent CLI noise from turn output."""
import re


def strip(output, **kwargs):
    output = re.sub(r'\x1b\[[0-9;]*m', '', output)
    lines = []
    for line in output.splitlines():
        s = line.strip()
        if s.startswith("⚠ tirith") or s.startswith("┊") or s.startswith("a/") or s.startswith("@@"):
            continue
        if s.startswith("+") and not s.startswith("+ "):
            continue
        lines.append(line)
    output = "\n".join(lines)
    output = re.sub(r'<\|[^|]+\|>', '', output)
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines).strip()
