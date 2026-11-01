FROM node:24-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates git python3 ripgrep \
  && rm -rf /var/lib/apt/lists/*

RUN npm install -g @earendil-works/pi-coding-agent

WORKDIR /workspace
ENTRYPOINT ["pi"]
CMD ["--mode", "rpc", "--no-extensions", "--no-session"]
