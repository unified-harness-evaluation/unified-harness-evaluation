FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN npm install -g @kilocode/cli --no-fund --no-audit
ENV HARNESS_NAME=kilocode HARNESS_TYPE=kilocode
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
