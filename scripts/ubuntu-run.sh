#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine and Docker Compose plugin first."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is not available."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  cat <<'EOF'
Docker CLI is installed, but the Docker daemon is not reachable.

Try:
  sudo systemctl enable --now docker
  sudo docker compose up -d --build

If you want to run Docker without sudo, add your login user to the docker group
and start a new shell session:
  sudo usermod -aG docker "$USER"

Note: the docker group has root-equivalent access. Prefer running deployment
commands with sudo on production servers.
EOF
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

docker compose up -d --build
docker compose ps
