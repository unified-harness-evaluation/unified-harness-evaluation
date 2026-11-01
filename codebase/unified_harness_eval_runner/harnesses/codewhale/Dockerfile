FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://codewhale.net/install.sh | sh \
    && ln -sf /root/.local/bin/codewhale /usr/local/bin/codewhale
ENV HARNESS_NAME=codewhale HARNESS_TYPE=codewhale
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
