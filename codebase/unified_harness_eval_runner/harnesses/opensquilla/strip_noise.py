#!/usr/bin/env python3
"""Strip opensquilla CLI noise from turn output."""
import re


def strip(output, **kwargs):
    output = re.sub(r'\x1b\[[0-9;]*m', '', output)
    output = output.replace("HEARTBEAT_OK", "")
    output = re.sub(r'<\|[^|]+\|>', '', output)
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines).strip()
