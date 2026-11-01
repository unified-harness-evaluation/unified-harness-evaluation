FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates zstd git && rm -rf /var/lib/apt/lists/*
RUN GROK_BIN_DIR=/usr/local/bin curl -fsSL https://x.ai/cli/install.sh | bash
ENV HARNESS_NAME=grok-build HARNESS_TYPE=grok-build
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
