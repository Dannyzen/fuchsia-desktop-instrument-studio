FROM docker.io/library/ubuntu@sha256:019e8eb29a85e74d64925745884f2ec79aa27e3feab36353d24656f4d6b89467

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl file git iproute2 jq openssh-client python3 unzip xz-utils \
    libglib2.0-0 libnss3 libx11-6 libxcomposite1 libxcursor1 libxi6 \
    libxrandr2 libxrender1 libxtst6 libasound2t64 libpulse0 \
    libgl1 libvulkan1 mesa-vulkan-drivers xvfb xauth socat \
    && rm -rf /var/lib/apt/lists/*

ARG CIPD_CLIENT_VERSION=xT2C5BmMILZveyhqRGQNh7RBoy8VfPf8yIM0QWvWNO0C
RUN curl -fsSL "https://chrome-infra-packages.appspot.com/client?platform=linux-amd64&version=${CIPD_CLIENT_VERSION}" \
    -o /usr/local/bin/cipd \
    && chmod 0755 /usr/local/bin/cipd \
    && cipd version

USER ubuntu
WORKDIR /workspace
ENV HOME=/home/ubuntu \
    FFX_ISOLATE_DIR=/workspace/state/ffx \
    XDG_CACHE_HOME=/workspace/cache \
    XDG_CONFIG_HOME=/workspace/state/config
CMD ["bash"]
