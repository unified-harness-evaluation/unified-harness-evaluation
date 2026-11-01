FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git bzip2 && rm -rf /var/lib/apt/lists/*
RUN export CONFIGURE=false && curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | bash && ln -sf /root/.local/bin/goose /usr/local/bin/goose
ENV HARNESS_NAME=goose HARNESS_TYPE=goose
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
