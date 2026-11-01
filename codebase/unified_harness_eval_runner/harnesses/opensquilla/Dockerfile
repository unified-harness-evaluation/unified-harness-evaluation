FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir opensquilla openai
ENV HARNESS_NAME=opensquilla HARNESS_TYPE=opensquilla
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
