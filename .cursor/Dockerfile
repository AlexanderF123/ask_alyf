# Adapted in part from frappe_docker (MIT):
# - images/bench/Dockerfile
# - images/custom/Containerfile
# https://github.com/frappe/frappe_docker

FROM python:3.14.3-slim-trixie

ARG NODE_VERSION=24.13.0

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/usr/local/bin:/home/frappe/.local/bin:${PATH}"
ENV UV_TOOL_BIN_DIR="/home/frappe/.local/bin"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        bash \
        build-essential \
        ca-certificates \
        cron \
        curl \
        file \
        git \
        jq \
        less \
        libbz2-dev \
        libffi-dev \
        libharfbuzz0b \
        libjpeg62-turbo-dev \
        liblcms2-dev \
        libldap2-dev \
        libmariadb-dev \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libpq-dev \
        libsasl2-dev \
        libsqlite3-dev \
        libssl-dev \
        libtiff-dev \
        libwebp-dev \
        mariadb-client \
        mariadb-server \
        media-types \
        pkg-config \
        procps \
        redis-server \
        redis-tools \
        ripgrep \
        sudo \
        which \
        xz-utils \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="/usr/local/bin" sh

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" -o /tmp/node.tar.xz; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; \
    rm -f /tmp/node.tar.xz; \
    npm install -g yarn

RUN useradd -ms /bin/bash frappe \
    && echo "frappe ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER frappe
WORKDIR /home/frappe
