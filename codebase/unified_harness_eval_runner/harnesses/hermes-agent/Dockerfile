FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir hermes-agent
ENV HARNESS_NAME=hermes-agent HARNESS_TYPE=hermes-agent
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
