FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code --no-fund --no-audit
RUN useradd -m -s /bin/bash coder
ENV HARNESS_NAME=claude-code HARNESS_TYPE=claude-code
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
