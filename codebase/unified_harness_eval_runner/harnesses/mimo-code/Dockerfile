FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN npm install -g @mimo-ai/cli --no-fund --no-audit
ENV HARNESS_NAME=mimo-code HARNESS_TYPE=mimo-code
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
