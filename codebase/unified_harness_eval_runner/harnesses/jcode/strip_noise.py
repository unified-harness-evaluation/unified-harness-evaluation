#!/usr/bin/env python3
"""Strip jcode CLI noise from turn output."""
import re


def strip(output, **kwargs):
    output = re.sub(r'\x1b\[[0-9;]*m', '', output)
    output = re.sub(r'^\[(?:write|Tokens|read|bash|skill_manage)\].*$', '', output, flags=re.MULTILINE)
    output = re.sub(r'^\$ .*$', '', output, flags=re.MULTILINE)
    output = re.sub(r'^  →\s.*$', '', output, flags=re.MULTILINE)
    output = re.sub(r'<\|[^|]+\|>', '', output)
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines).strip()
