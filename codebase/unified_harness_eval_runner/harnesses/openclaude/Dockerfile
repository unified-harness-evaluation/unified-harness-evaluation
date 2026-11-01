FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN npm install -g @gitlawb/openclaude --no-fund --no-audit
RUN useradd -m -s /bin/bash coder
ENV HARNESS_NAME=openclaude HARNESS_TYPE=openclaude
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
