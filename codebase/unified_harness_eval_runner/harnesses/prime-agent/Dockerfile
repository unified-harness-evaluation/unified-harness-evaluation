FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates nodejs git && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh \
    && ln -sf $(find /root -name prime-agent -type f | head -1) /usr/local/bin/prime-agent
ENV HARNESS_NAME=prime-agent HARNESS_TYPE=prime-agent
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
