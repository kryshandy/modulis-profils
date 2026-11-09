#!/usr/bin/env bash
# Installe Docker Engine + Compose dans Ubuntu (WSL2) depuis le dépôt officiel de Docker.
# Source : https://docs.docker.com/engine/install/ubuntu/
set -euo pipefail

echo ">> Paquets prérequis"
sudo apt-get update
sudo apt-get install -y ca-certificates curl

echo ">> Clé GPG officielle de Docker"
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo ">> Dépôt apt Docker"
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

echo ">> Installation"
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo ">> Utiliser docker sans sudo"
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

echo ">> Terminé. Fermez puis rouvrez WSL (wsl --shutdown) pour que le groupe docker soit pris en compte."
sudo docker run --rm hello-world
