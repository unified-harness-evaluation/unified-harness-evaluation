FROM python:3.12-slim-bookworm
ENV BUN_INSTALL=/opt/bun PATH=/opt/bun/bin:/usr/local/bin:/usr/bin:/bin
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip git && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://bun.sh/install | bash -s "bun-v1.4.2"
RUN bun install -g @oh-my-pi/pi-coding-agent
ENV HARNESS_NAME=oh-my-pi HARNESS_TYPE=oh-my-pi
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
