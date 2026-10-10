#!/usr/bin/env bash
# Первичная настройка чистой ВМ Ubuntu 22.04/24.04 в Yandex Cloud.
# Запуск: bash deploy/scripts/setup_vm.sh   (под обычным пользователем с sudo)
set -euo pipefail

echo "==> Обновление системы"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git unzip sqlite3 unattended-upgrades

echo "==> Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

echo "==> Swap 2 ГБ (страховка для ВМ с 2 ГБ RAM)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Автоматические обновления безопасности"
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> SSH: вход только по ключу"
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl reload ssh || sudo systemctl reload sshd || true

echo
echo "Готово. Выйдите из SSH и зайдите снова, чтобы группа docker применилась:"
echo "  exit  →  ssh <user>@<IP>  →  docker ps"
