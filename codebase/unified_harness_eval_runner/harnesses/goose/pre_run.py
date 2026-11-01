#!/usr/bin/env python3
import os
import sys
from pathlib import Path

for home in [Path.home(), Path("/home/goose")]:
    cfg = home / ".config" / "goose" / "config.yaml"
    if cfg.exists():
        cfg.unlink()

sys.path.insert(0, "/tmp")
import container_setup
container_setup.finalize_workspace()
