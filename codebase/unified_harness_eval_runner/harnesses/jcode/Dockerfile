FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git curl socat && rm -rf /var/lib/apt/lists/*
ARG JCODE_VERSION=v0.90.0
ARG TARGETARCH
RUN ARCH=$(case "$TARGETARCH" in arm64) echo aarch64;; amd64) echo x86_64;; *) echo "$TARGETARCH";; esac) && \
    curl -fsSL "https://github.com/1jehuang/jcode/releases/download/${JCODE_VERSION}/jcode-linux-${ARCH}.tar.gz" \
    | tar xz -C /usr/local/bin/ && \
    mv /usr/local/bin/jcode-linux-${ARCH} /usr/local/bin/jcode && \
    chmod +x /usr/local/bin/jcode
ENV HARNESS_NAME=jcode HARNESS_TYPE=jcode
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
