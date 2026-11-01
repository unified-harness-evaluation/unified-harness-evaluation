FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir mistral-vibe
ENV HARNESS_NAME=mistral-vibe HARNESS_TYPE=mistral-vibe
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
