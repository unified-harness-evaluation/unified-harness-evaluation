import os
import shutil


class HarnessError(RuntimeError):
    """Raised on container lifecycle failures."""


def _resolve_docker() -> str:
    """Locate the docker binary.

    Shell aliases (e.g. Docker Desktop's) are not visible to subprocess calls,
    so fall back to known install locations if docker isn't on PATH. Override
    with the DOCKER environment variable if yours lives elsewhere.
    """
    env = os.environ.get("DOCKER")
    if env and os.path.isfile(env) and os.access(env, os.X_OK):
        return env
    found = shutil.which("docker")
    if found:
        return found
    for cand in (
        "/Applications/Docker.app/Contents/Resources/bin/docker",
        "/usr/local/bin/docker",
        "/opt/homebrew/bin/docker",
        os.path.expanduser("~/.docker/bin/docker"),
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    # Last resort: bare name, so the resulting error is the familiar one.
    return "docker"


# Resolved once at import. All docker subprocess calls use this instead of the
# bare "docker" string so they work even when docker is only a shell alias.
DOCKER = _resolve_docker()
