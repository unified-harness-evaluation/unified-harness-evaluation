#!/usr/bin/env bash
# Build Docker images for harnesses.
#
# Each harness lives in harnesses/<harness>/ with its own Dockerfile and a
# harness.yaml declaring `image: harness-<harness>`. The gateway (harness_server.py)
# runs containers from that exact tag, so the tag must be harness-<harness>.
#
# Usage:
#   ./build.sh                 # build all harnesses
#   ./build.sh goose codex     # build only the named harnesses

set -u

cd "$(dirname "$0")" || exit 1

# Resolve the docker binary. Shell aliases (e.g. Docker Desktop's) are not visible
# to scripts, so fall back to known install locations if docker isn't on PATH.
# Override with DOCKER=/path/to/docker if yours lives elsewhere.
DOCKER="${DOCKER:-}"
if [ -z "$DOCKER" ]; then
  # type -P finds only real executables on PATH (ignores aliases/functions).
  DOCKER="$(type -P docker || true)"
fi
if [ -z "$DOCKER" ] || [ ! -x "$DOCKER" ]; then
  for cand in \
    /Applications/Docker.app/Contents/Resources/bin/docker \
    /usr/local/bin/docker \
    /opt/homebrew/bin/docker \
    "$HOME/.docker/bin/docker"; do
    if [ -x "$cand" ]; then
      DOCKER="$cand"
      break
    fi
  done
fi
if [ -z "$DOCKER" ] || ! "$DOCKER" version >/dev/null 2>&1; then
  echo "ERROR: docker not found or not running." >&2
  echo "Install Docker Desktop, start it, or set DOCKER=/path/to/docker." >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  harnesses=("$@")
else
  harnesses=()
  for d in harnesses/*/; do
    harnesses+=("$(basename "$d")")
  done
fi

failed=()
for h in "${harnesses[@]}"; do
  dir="harnesses/$h"
  if [ ! -f "$dir/Dockerfile" ]; then
    echo "SKIP: no Dockerfile at $dir"
    continue
  fi
  echo "=== building harness-$h ==="
  if "$DOCKER" build -t "harness-$h" -f "$dir/Dockerfile" "$dir"; then
    echo "OK: harness-$h"
  else
    echo "FAILED: harness-$h"
    failed+=("$h")
  fi
done

echo
if [ "${#failed[@]}" -eq 0 ]; then
  echo "All builds succeeded."
else
  echo "Failed: ${failed[*]}"
  exit 1
fi
