FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN npm install -g @qwen-code/qwen-code --no-fund --no-audit
ENV HARNESS_NAME=qwen-code HARNESS_TYPE=qwen-code
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
